"""Semantic evidence repository ports and in-memory implementation."""

from __future__ import annotations

from typing import Protocol

from .semantic_models import (
    BasicInfoInterpretation,
    BlockInterpretation,
    TableInterpretation,
    TextObservation,
)
from .tool_models import ToolModelError


class SemanticEvidenceRepositoryPort(Protocol):
    """Persistence boundary for graph-internal TextObservation evidence."""

    def save_observations(self, observations: tuple[TextObservation, ...]) -> tuple[TextObservation, ...]:
        """Persist semantic observations."""

    def find_by_page(self, page_id: str) -> tuple[TextObservation, ...]:
        """Find observations attached to one page."""

    def find_by_element(self, element_id: str) -> tuple[TextObservation, ...]:
        """Find observations attached to one source element."""

    def find_by_run(self, recognition_run_id: str) -> tuple[TextObservation, ...]:
        """Find observations produced by one graph-external recognition run."""

    def save_interpretations(
        self,
        interpretations: tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...],
    ) -> tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...]:
        """Persist structured interpretations."""

    def find_interpretations(
        self,
        *,
        page_id: str | None = None,
        element_id: str | None = None,
        recognition_run_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...]:
        """Find interpretations by page, source element, run, or status."""


class SectionMatchWritePort(Protocol):
    """Controlled write boundary for section-caption semantic relations."""

    def write_section_relation(
        self,
        *,
        relation_type: str,
        start_id: str,
        end_id: str,
        properties: dict[str, object],
    ) -> None:
        """Write one whitelisted section candidate or formal relation."""


class SectionMatchQueryPort(Protocol):
    """Read boundary for section-caption match projections."""

    def list_section_matches(
        self,
        *,
        cross_section_id: str | None = None,
        page_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[object, ...]:
        """Return section match summaries without writing."""


class InMemorySemanticEvidenceRepository:
    """In-memory semantic evidence repository for unit tests."""

    def __init__(self, fail_writes: bool = False):
        self.fail_writes = fail_writes
        self._observations: dict[str, TextObservation] = {}
        self._interpretations: dict[str, BlockInterpretation | BasicInfoInterpretation | TableInterpretation] = {}

    def save_observations(self, observations: tuple[TextObservation, ...]) -> tuple[TextObservation, ...]:
        if self.fail_writes:
            raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence repository is unavailable")
        if not isinstance(observations, tuple) or not all(isinstance(item, TextObservation) for item in observations):
            raise ToolModelError("invalid_observations", "observations must be a tuple of TextObservation")
        for item in observations:
            self._observations[item.observation_id] = item
        return observations

    def find_by_page(self, page_id: str) -> tuple[TextObservation, ...]:
        return tuple(item for item in self._observations.values() if item.page_id == page_id)

    def find_by_element(self, element_id: str) -> tuple[TextObservation, ...]:
        return tuple(item for item in self._observations.values() if item.target_element_id == element_id)

    def find_by_run(self, recognition_run_id: str) -> tuple[TextObservation, ...]:
        return tuple(item for item in self._observations.values() if item.recognition_run_id == recognition_run_id)

    def save_interpretations(
        self,
        interpretations: tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...],
    ) -> tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...]:
        if self.fail_writes:
            raise ToolModelError("SEMANTIC_EVIDENCE_UNAVAILABLE", "semantic evidence repository is unavailable")
        _require_interpretation_tuple(interpretations)
        for item in interpretations:
            self._interpretations[item.interpretation_id] = item
        return interpretations

    def find_interpretations(
        self,
        *,
        page_id: str | None = None,
        element_id: str | None = None,
        recognition_run_id: str | None = None,
        statuses: tuple[str, ...] | None = None,
    ) -> tuple[BlockInterpretation | BasicInfoInterpretation | TableInterpretation, ...]:
        results = list(self._interpretations.values())
        if page_id is not None:
            results = [item for item in results if item.page_id == page_id]
        if element_id is not None:
            results = [item for item in results if _source_element_id(item) == element_id]
        if recognition_run_id is not None:
            results = [item for item in results if item.recognition_run_id == recognition_run_id]
        if statuses is not None:
            allowed_statuses = set(statuses)
            results = [item for item in results if item.analysis_status.value in allowed_statuses]
        return tuple(results)


def _require_interpretation_tuple(values: object) -> None:
    if not isinstance(values, tuple) or not all(
        isinstance(item, (BlockInterpretation, BasicInfoInterpretation, TableInterpretation)) for item in values
    ):
        raise ToolModelError("invalid_interpretations", "interpretations must be a tuple of interpretation DTOs")


def _source_element_id(
    item: BlockInterpretation | BasicInfoInterpretation | TableInterpretation,
) -> str:
    if isinstance(item, BlockInterpretation):
        return item.block_id
    if isinstance(item, BasicInfoInterpretation):
        return item.basic_info_id
    return item.table_id


__all__ = (
    "InMemorySemanticEvidenceRepository",
    "SectionMatchQueryPort",
    "SectionMatchWritePort",
    "SemanticEvidenceRepositoryPort",
)
