"""Graph-external RecognitionRun log ports and in-memory implementation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from uuid import uuid4

from .semantic_models import RecognitionRunSummary
from .tool_models import ToolModelError


class RecognitionRunLogPort(Protocol):
    """Persistence boundary for graph-external recognition run logs."""

    def create_run(
        self,
        page_id: str,
        model_profile: str,
        prompt_version: str,
        input_refs: Mapping[str, Any],
        write_back: bool,
        *,
        run_type: str = "recognition",
        target_scope: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        cost_summary: Mapping[str, Any] | None = None,
        attempt_ids: tuple[str, ...] = (),
        usage_summary=None,
        latency_summary=None,
        input_contract_version: str = "1",
        output_contract_version: str = "1",
        preprocessing_version: str = "preprocess-v1",
        payload_ref: str | None = None,
    ) -> RecognitionRunSummary:
        """Create a pending graph-external run log."""

    def complete_run(
        self,
        recognition_run_id: str,
        model_name: str | None = None,
        model_version: str | None = None,
        attempt_ids: tuple[str, ...] | None = None,
        usage_summary=None,
        latency_summary=None,
        payload_ref: str | None = None,
        input_contract_version: str | None = None,
        output_contract_version: str | None = None,
        preprocessing_version: str | None = None,
    ) -> RecognitionRunSummary:
        """Mark a run as succeeded."""

    def fail_run(self, recognition_run_id: str, error_summary: str) -> RecognitionRunSummary:
        """Mark a run as failed."""

    def get_run(self, recognition_run_id: str) -> RecognitionRunSummary:
        """Return one run or raise a classified not-found error."""


class InMemoryRecognitionRunLog:
    """Simple graph-external run log used by unit tests."""

    def __init__(self):
        self._runs: dict[str, RecognitionRunSummary] = {}

    def create_run(
        self,
        page_id: str,
        model_profile: str,
        prompt_version: str,
        input_refs: Mapping[str, Any],
        write_back: bool,
        *,
        run_type: str = "recognition",
        target_scope: str | None = None,
        model_name: str | None = None,
        model_version: str | None = None,
        cost_summary: Mapping[str, Any] | None = None,
        attempt_ids: tuple[str, ...] = (),
        usage_summary=None,
        latency_summary=None,
        input_contract_version: str = "1",
        output_contract_version: str = "1",
        preprocessing_version: str = "preprocess-v1",
        payload_ref: str | None = None,
    ) -> RecognitionRunSummary:
        now = _now()
        run = RecognitionRunSummary(
            recognition_run_id=f"run:{uuid4()}",
            run_type=run_type,
            page_id=page_id,
            model_profile=model_profile,
            prompt_version=prompt_version,
            status="partial",
            write_back=write_back,
            model_name=model_name,
            model_version=model_version,
            input_refs=input_refs,
            started_at=now,
            target_scope=target_scope,
            cost_summary=cost_summary,
            attempt_ids=attempt_ids,
            usage_summary=usage_summary,
            latency_summary=latency_summary,
            input_contract_version=input_contract_version,
            output_contract_version=output_contract_version,
            preprocessing_version=preprocessing_version,
            payload_ref=payload_ref,
        )
        self._runs[run.recognition_run_id] = run
        return run

    def complete_run(
        self,
        recognition_run_id: str,
        model_name: str | None = None,
        model_version: str | None = None,
        attempt_ids: tuple[str, ...] | None = None,
        usage_summary=None,
        latency_summary=None,
        payload_ref: str | None = None,
        input_contract_version: str | None = None,
        output_contract_version: str | None = None,
        preprocessing_version: str | None = None,
    ) -> RecognitionRunSummary:
        run = self.get_run(recognition_run_id)
        updated = RecognitionRunSummary(
            recognition_run_id=run.recognition_run_id,
            run_type=run.run_type,
            page_id=run.page_id,
            model_profile=run.model_profile,
            prompt_version=run.prompt_version,
            status="succeeded",
            write_back=run.write_back,
            model_name=model_name,
            model_version=model_version,
            error_summary=run.error_summary,
            input_refs=run.input_refs,
            started_at=run.started_at,
            finished_at=_now(),
            target_scope=run.target_scope,
            cost_summary=run.cost_summary,
            attempt_ids=run.attempt_ids if attempt_ids is None else tuple(attempt_ids),
            usage_summary=run.usage_summary if usage_summary is None else usage_summary,
            latency_summary=run.latency_summary if latency_summary is None else latency_summary,
            input_contract_version=(
                run.input_contract_version
                if input_contract_version is None
                else input_contract_version
            ),
            output_contract_version=(
                run.output_contract_version
                if output_contract_version is None
                else output_contract_version
            ),
            preprocessing_version=(
                run.preprocessing_version
                if preprocessing_version is None
                else preprocessing_version
            ),
            payload_ref=run.payload_ref if payload_ref is None else payload_ref,
        )
        self._runs[recognition_run_id] = updated
        return updated

    def fail_run(self, recognition_run_id: str, error_summary: str) -> RecognitionRunSummary:
        run = self.get_run(recognition_run_id)
        updated = RecognitionRunSummary(
            recognition_run_id=run.recognition_run_id,
            run_type=run.run_type,
            page_id=run.page_id,
            model_profile=run.model_profile,
            prompt_version=run.prompt_version,
            status="failed",
            write_back=run.write_back,
            model_name=run.model_name,
            model_version=run.model_version,
            error_summary=error_summary,
            input_refs=run.input_refs,
            started_at=run.started_at,
            finished_at=_now(),
            target_scope=run.target_scope,
            cost_summary=run.cost_summary,
        )
        self._runs[recognition_run_id] = updated
        return updated

    def get_run(self, recognition_run_id: str) -> RecognitionRunSummary:
        try:
            return self._runs[recognition_run_id]
        except KeyError as exc:
            raise ToolModelError("NOT_FOUND", "recognition run was not found") from exc


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ("InMemoryRecognitionRunLog", "RecognitionRunLogPort")
