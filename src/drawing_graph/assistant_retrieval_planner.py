"""Read-only graph retrieval planner for the product assistant layer.

规划器只负责把 ``EvidenceRequirement`` 转为受控只读 ``RetrievalPlan``，
不访问 ``DrawingGraphToolFacade``、不调用 Qwen、不读写图谱数据库、
不创建 ``RecognitionRun``，也不消费任何写回授权。
"""

from __future__ import annotations

from .assistant_models import (
    AssistantScope,
    EvidenceRequirement,
    EvidenceType,
    PlanWarning,
    QuestionUnderstandingResult,
    ReasonCode,
    RetrievalPlan,
    RetrievalPolicy,
    RetrievalStep,
)


class RetrievalPlanner:
    """把证据需求映射为最小只读检索计划。"""

    def plan(
        self,
        question_result: QuestionUnderstandingResult,
        policy: RetrievalPolicy | None = None,
    ) -> RetrievalPlan:
        policy = policy or RetrievalPolicy()
        warnings: list[PlanWarning] = []
        steps = []
        for requirement in question_result.required_evidence:
            warning = self._scope_issue(requirement)
            if warning is not None:
                warnings.append(warning)
                continue
            mapped_steps = self._map_requirement(requirement, policy)
            steps.extend(mapped_steps)
        merged_steps = _merge_steps(steps)
        return RetrievalPlan(
            request_id=question_result.request_id,
            steps=tuple(merged_steps),
            dedupe_keys=tuple(step.dedupe_key for step in merged_steps if step.dedupe_key),
            warnings=tuple(warnings),
        )

    def _scope_issue(self, requirement: EvidenceRequirement) -> PlanWarning | None:
        """校验需求 scope；缺失返回 ``scope_missing``，冲突返回 ``scope_conflict``。"""

        evidence_type = requirement.evidence_type
        scope = requirement.target_scope

        if evidence_type is EvidenceType.PROJECT_DRAWING_SETS:
            if scope.project_id is None:
                return self._missing(requirement, "project_id 是项目图纸册证据需求的必需 scope")
            return None

        if evidence_type is EvidenceType.DRAWING_SET_PAGES:
            if scope.drawing_set_id is None:
                return self._missing(requirement, "drawing_set_id 是图纸册页面证据需求的必需 scope")
            return None

        if evidence_type is EvidenceType.PAGE_SOURCE_FACTS:
            if scope.page_id is None:
                return self._missing(requirement, "page_id 是页面来源事实证据需求的必需 scope")
            if scope.block_id is not None or scope.element_id is not None:
                return self._conflict(requirement, "页面来源事实需求不能同时携带 page_id 与 block_id/element_id 目标")
            return None

        if evidence_type in (EvidenceType.BLOCK_TRACE, EvidenceType.BLOCK_RELATIONS):
            if scope.block_id is None:
                return self._missing(requirement, "block_id 是图块证据需求的必需 scope")
            return None

        if evidence_type in (
            EvidenceType.TEXT_OBSERVATIONS,
            EvidenceType.STRUCTURED_INTERPRETATIONS,
        ):
            supplied = sum(value is not None for value in (scope.page_id, scope.element_id))
            if supplied == 0:
                return self._missing(requirement, "文字观察/结构化解释需求需要 page_id 或 element_id")
            if supplied > 1:
                return self._conflict(requirement, "文字观察/结构化解释需求不能同时携带 page_id 与 element_id")
            return None

        if evidence_type is EvidenceType.CANDIDATE_RELATIONS:
            if scope.page_id is None and scope.block_id is None:
                return self._missing(requirement, "候选关系需求需要 page_id 或 block_id")
            return None

        if evidence_type is EvidenceType.SECTION_MATCHES:
            if scope.cross_section_id is None and scope.page_id is None:
                return self._missing(requirement, "断面匹配需求需要 cross_section_id 或 page_id")
            return None

        if evidence_type is EvidenceType.SEMANTIC_PAYLOAD:
            if not requirement.include_payload:
                return None
            if requirement.payload_ref is None:
                return self._missing(requirement, "include_payload=True 的语义 payload 需求需要 payload_ref")
            return None

        return None

    def _map_requirement(
        self,
        requirement: EvidenceRequirement,
        policy: RetrievalPolicy,
    ):
        """把证据需求映射为 facade 白名单中的只读步骤。"""

        evidence_type = requirement.evidence_type
        scope = requirement.target_scope

        if evidence_type is EvidenceType.PROJECT_DRAWING_SETS:
            method = "list_drawing_sets"
            step_limit = min(
                requirement.limit or policy.default_limit,
                policy.max_limit,
            )
            parameters = {
                "project_id": scope.project_id,
                "limit": step_limit,
            }
        elif evidence_type is EvidenceType.DRAWING_SET_PAGES:
            method = "list_pages"
            step_limit = min(
                requirement.limit or policy.default_limit,
                policy.max_limit,
            )
            parameters = {
                "drawing_set_id": scope.drawing_set_id,
                "limit": step_limit,
            }
        elif evidence_type is EvidenceType.PAGE_SOURCE_FACTS:
            method = "get_page_source_facts"
            parameters = {
                "page_id": scope.page_id,
                "element_types": None,
                "include_image_meta": True,
            }
        elif evidence_type is EvidenceType.BLOCK_TRACE:
            method = "get_block_trace"
            parameters = {"block_id": scope.block_id}
        elif evidence_type is EvidenceType.BLOCK_RELATIONS:
            method = "get_block_relations"
            parameters = {"block_id": scope.block_id}
        elif evidence_type is EvidenceType.TEXT_OBSERVATIONS:
            method = "list_text_observations"
            parameters = {
                "page_id": scope.page_id,
                "element_id": scope.element_id,
                "recognition_run_id": None,
                "statuses": None,
            }
            steps = [
                self._semantic_step(
                    requirement,
                    method,
                    parameters,
                    policy,
                )
            ]
            if scope.page_id is not None:
                steps.append(
                    self._locate_step(requirement, policy)
                )
            return steps
        elif evidence_type is EvidenceType.STRUCTURED_INTERPRETATIONS:
            method = "list_interpretations"
            parameters = {
                "page_id": scope.page_id,
                "element_id": scope.element_id,
                "recognition_run_id": None,
                "statuses": None,
            }
            steps = [
                self._semantic_step(
                    requirement,
                    method,
                    parameters,
                    policy,
                )
            ]
            if scope.page_id is not None:
                steps.append(
                    self._locate_step(requirement, policy)
                )
            return steps
        elif evidence_type is EvidenceType.SEMANTIC_PAYLOAD:
            if not requirement.include_payload or requirement.payload_ref is None:
                return []
            method = "get_semantic_payload"
            parameters = {"payload_ref": requirement.payload_ref}
        elif evidence_type is EvidenceType.CANDIDATE_RELATIONS:
            method = "list_candidate_relations"
            parameters = {
                "page_id": scope.page_id,
                "block_id": scope.block_id,
                "relation_type": None,
                "status": None,
            }
        elif evidence_type is EvidenceType.SECTION_MATCHES:
            method = "list_section_matches"
            parameters = {
                "cross_section_id": scope.cross_section_id,
                "page_id": scope.page_id,
                "statuses": None,
            }
        else:
            return []

        step_limit = (
            None
            if evidence_type
            not in (EvidenceType.PROJECT_DRAWING_SETS, EvidenceType.DRAWING_SET_PAGES)
            else min(
                requirement.limit or policy.default_limit,
                policy.max_limit,
            )
        )
        dedupe_key = _dedupe_key(method, parameters)
        return [
            self._semantic_step(
                requirement,
                method,
                parameters,
                policy,
                step_limit=step_limit,
                dedupe_key=dedupe_key,
            )
        ]

    @staticmethod
    def _semantic_step(
        requirement: EvidenceRequirement,
        method: str,
        parameters: dict[str, object],
        policy: RetrievalPolicy,
        *,
        step_limit: int | None = None,
        dedupe_key: str | None = None,
    ) -> RetrievalStep:
        """构造一个只读检索步骤，保留原始 requirement_id 用于决策层回溯。"""

        del policy
        return RetrievalStep(
            step_id=f"step:{requirement.requirement_id}",
            facade_method=method,
            scope=requirement.target_scope,
            parameters=parameters,
            required=requirement.required,
            limit=step_limit,
            include_payload=requirement.include_payload,
            requirement_ids=(requirement.requirement_id,),
            dedupe_key=dedupe_key or _dedupe_key(method, parameters),
        )

    @staticmethod
    def _locate_step(
        requirement: EvidenceRequirement,
        policy: RetrievalPolicy,
    ) -> RetrievalStep:
        """为页面级语义需求附加定位来源事实步骤（含图片元数据）。"""

        del policy
        page_id = requirement.target_scope.page_id
        parameters = {
            "page_id": page_id,
            "element_types": None,
            "include_image_meta": True,
        }
        return RetrievalStep(
            step_id=f"step:{requirement.requirement_id}:locate",
            facade_method="get_page_source_facts",
            scope=AssistantScope(page_id=page_id),
            parameters=parameters,
            required=requirement.required,
            include_payload=requirement.include_payload,
            requirement_ids=(requirement.requirement_id,),
            dedupe_key=_dedupe_key("get_page_source_facts", parameters),
        )

    @staticmethod
    def _missing(requirement: EvidenceRequirement, message: str) -> PlanWarning:
        return PlanWarning(
            reason_code=ReasonCode.SCOPE_MISSING,
            message=message,
            requirement_id=requirement.requirement_id,
        )

    @staticmethod
    def _conflict(requirement: EvidenceRequirement, message: str) -> PlanWarning:
        return PlanWarning(
            reason_code=ReasonCode.SCOPE_CONFLICT,
            message=message,
            requirement_id=requirement.requirement_id,
        )


def _dedupe_key(method: str, parameters: dict[str, object]) -> str:
    """生成稳定去重 key：facade 方法 + 排序后的参数。"""

    encoded = ",".join(f"{key}={value!r}" for key, value in sorted(parameters.items()))
    return f"{method}:{encoded}"


def _merge_steps(steps: list[RetrievalStep]) -> list[RetrievalStep]:
    """按 dedupe_key 合并相同只读查询，保留全部 requirement_ids。"""

    merged: list[RetrievalStep] = []
    by_key: dict[str, int] = {}
    for step in steps:
        if step.dedupe_key is None or step.dedupe_key not in by_key:
            if step.dedupe_key is not None:
                by_key[step.dedupe_key] = len(merged)
            merged.append(step)
            continue
        index = by_key[step.dedupe_key]
        existing = merged[index]
        limits = [value for value in (existing.limit, step.limit) if value is not None]
        merged[index] = RetrievalStep(
            step_id=existing.step_id,
            facade_method=existing.facade_method,
            scope=existing.scope,
            parameters=existing.parameters,
            required=existing.required or step.required,
            depends_on=existing.depends_on,
            limit=min(limits) if limits else None,
            include_payload=existing.include_payload or step.include_payload,
            requirement_ids=existing.requirement_ids + step.requirement_ids,
            dedupe_key=existing.dedupe_key,
        )
    return merged
