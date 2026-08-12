"""Recognition cost/latency estimation and budget gating for the gap loop.

估算器使用可注入的 ``RecognitionCostProfile`` 按任务类型、模型 profile 与
图片范围给出保守成本/时延估算；无 profile 时返回 ``estimate_unavailable``，
不假设零成本。门控只做确定性决策，不读取供应商密钥、不请求网络、
不写缓存或图谱，实际账单由后续执行/追溯模块记录。
"""

from __future__ import annotations

import dataclasses
from typing import Mapping

from .assistant_models import (
    EstimateStatus,
    ReasonCode,
    RecognitionEstimate,
    RecognitionPolicy,
    RecognitionTarget,
    RecognitionTargetStatus,
)


@dataclasses.dataclass(frozen=True)
class RecognitionCostProfile:
    """可注入的保守成本/时延估算配置，价格与模型能力不硬编码在算法内。"""

    task_cost: Mapping[str, float] = dataclasses.field(default_factory=dict)
    task_latency_ms: Mapping[str, float] = dataclasses.field(default_factory=dict)
    model_cost_multiplier: Mapping[str, float] = dataclasses.field(default_factory=dict)
    model_latency_multiplier: Mapping[str, float] = dataclasses.field(default_factory=dict)
    area_cost_factor: float = 0.0
    area_latency_factor: float = 0.0
    currency: str = "CNY"
    estimator_version: str = "semantic-gap-estimator-v1"

    def __post_init__(self) -> None:
        for field_name in (
            "task_cost",
            "task_latency_ms",
            "model_cost_multiplier",
            "model_latency_multiplier",
        ):
            values = getattr(self, field_name)
            if not isinstance(values, Mapping):
                raise ValueError(f"{field_name} must be a mapping")
            for key, value in values.items():
                if not isinstance(key, str) or not key.strip():
                    raise ValueError(f"{field_name} keys must be non-empty strings")
                if (
                    not isinstance(value, (int, float))
                    or isinstance(value, bool)
                    or value < 0
                ):
                    raise ValueError(f"{field_name} values must be non-negative numbers")
        for field_name in ("area_cost_factor", "area_latency_factor"):
            value = getattr(self, field_name)
            if (
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or value < 0
            ):
                raise ValueError(f"{field_name} must be a non-negative number")
        _require_text(self.currency, "currency")
        _require_text(self.estimator_version, "estimator_version")


class RecognitionEstimator:
    """按 task type、model profile 与图片范围给出保守估算。"""

    def estimate(
        self,
        target: RecognitionTarget,
        profile: RecognitionCostProfile | None = None,
        *,
        model_profile: str | None = None,
        retry_count: int = 0,
    ) -> tuple[float, float] | None:
        """返回 (成本, 时延毫秒)；无法估算时返回 None。"""

        if profile is None:
            return None
        task_type = target.task_type
        if (
            task_type not in profile.task_cost
            or task_type not in profile.task_latency_ms
        ):
            return None
        cost = float(profile.task_cost[task_type])
        latency = float(profile.task_latency_ms[task_type])
        if model_profile is not None:
            cost *= float(profile.model_cost_multiplier.get(model_profile, 1.0))
            latency *= float(profile.model_latency_multiplier.get(model_profile, 1.0))
        area = RecognitionEstimator._image_area(target)
        cost += float(profile.area_cost_factor) * area
        retries = max(0, int(retry_count))
        latency = latency * (1 + retries) + float(profile.area_latency_factor) * area
        return round(cost, 6), round(latency, 3)

    @staticmethod
    def _image_area(target: RecognitionTarget) -> float:
        """按规范化 bbox 面积估算图片范围；无 bbox 时按整页 1.0。"""

        bbox = target.normalized_bbox or target.bbox
        if bbox is None:
            return 1.0
        try:
            width = float(bbox["x_max"]) - float(bbox["x_min"])
            height = float(bbox["y_max"]) - float(bbox["y_min"])
            return max(0.0, width * height)
        except (KeyError, TypeError, ValueError):
            return 1.0


class RecognitionBudgetEvaluator:
    """执行授权、目标数、成本与时延硬门控，输出 selected/deferred 拆分。"""

    def __init__(
        self,
        estimator: RecognitionEstimator | None = None,
        profile: RecognitionCostProfile | None = None,
    ):
        self.estimator = estimator or RecognitionEstimator()
        self.profile = profile

    def evaluate(
        self,
        targets: tuple[RecognitionTarget, ...],
        policy: RecognitionPolicy,
    ) -> tuple[
        tuple[RecognitionTarget, ...],
        tuple[RecognitionTarget, ...],
        RecognitionEstimate,
    ]:
        """按策略门控目标，返回 (selected, deferred, estimate)。"""

        if not policy.allow_recognition:
            deferred = tuple(
                self._deferred(target, ReasonCode.RECOGNITION_FORBIDDEN)
                for target in targets
            )
            return (
                (),
                deferred,
                RecognitionEstimate(
                    status=EstimateStatus.NOT_REQUIRED,
                    selected_target_count=0,
                    deferred_target_count=len(deferred),
                    currency=self._currency(),
                    estimator_version=self._estimator_version(),
                    reason_codes=(ReasonCode.RECOGNITION_FORBIDDEN,),
                ),
            )
        selected: list[RecognitionTarget] = []
        deferred: list[RecognitionTarget] = []
        gate_reasons: list[ReasonCode] = []
        total_cost = 0.0
        total_latency_ms = 0.0
        estimated = True
        hard_budget = (
            policy.max_estimated_cost is not None
            or policy.max_latency_seconds is not None
        )
        for target in targets:
            if target.status is RecognitionTargetStatus.BLOCKED:
                continue
            if policy.max_targets is not None and len(selected) >= policy.max_targets:
                deferred.append(self._deferred(target, ReasonCode.BUDGET_EXCEEDED))
                gate_reasons.append(ReasonCode.BUDGET_EXCEEDED)
                continue
            estimate = self.estimator.estimate(
                target,
                self.profile,
                model_profile=policy.model_profile,
                retry_count=policy.retry_count,
            )
            if estimate is None:
                estimated = False
                if hard_budget:
                    deferred.append(
                        self._deferred(target, ReasonCode.ESTIMATE_UNAVAILABLE)
                    )
                    gate_reasons.append(ReasonCode.ESTIMATE_UNAVAILABLE)
                    continue
                selected.append(target)
                continue
            cost, latency_ms = estimate
            if (
                policy.max_estimated_cost is not None
                and total_cost + cost > policy.max_estimated_cost
            ):
                deferred.append(self._deferred(target, ReasonCode.BUDGET_EXCEEDED))
                gate_reasons.append(ReasonCode.BUDGET_EXCEEDED)
                continue
            if (
                policy.max_latency_seconds is not None
                and latency_ms / 1000.0 > policy.max_latency_seconds
            ):
                deferred.append(self._deferred(target, ReasonCode.LATENCY_EXCEEDED))
                gate_reasons.append(ReasonCode.LATENCY_EXCEEDED)
                continue
            total_cost += cost
            total_latency_ms += latency_ms
            selected.append(target)
        status = (
            EstimateStatus.ESTIMATED
            if estimated
            else EstimateStatus.ESTIMATE_UNAVAILABLE
        )
        return (
            tuple(selected),
            tuple(deferred),
            RecognitionEstimate(
                status=status,
                selected_target_count=len(selected),
                deferred_target_count=len(deferred),
                estimated_cost=total_cost if estimated else None,
                estimated_latency_ms=total_latency_ms if estimated else None,
                currency=self._currency(),
                estimator_version=self._estimator_version(),
                reason_codes=tuple(dict.fromkeys(gate_reasons)),
            ),
        )

    @staticmethod
    def _deferred(
        target: RecognitionTarget,
        reason_code: ReasonCode,
    ) -> RecognitionTarget:
        """把目标标记为 deferred，保留 covered requirement IDs。"""

        return dataclasses.replace(
            target,
            status=RecognitionTargetStatus.DEFERRED,
            reason_codes=tuple(
                dict.fromkeys(target.reason_codes + (reason_code,))
            ),
        )

    def _currency(self) -> str | None:
        return self.profile.currency if self.profile is not None else None

    def _estimator_version(self) -> str:
        if self.profile is not None:
            return self.profile.estimator_version
        return "semantic-gap-estimator-v1"


def _require_text(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-empty string")
    return value


__all__ = (
    "RecognitionBudgetEvaluator",
    "RecognitionCostProfile",
    "RecognitionEstimator",
)
