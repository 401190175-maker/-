"""Immutable recognition task registry and task-specific contract specs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .recognition_models import RecognitionTaskType
from .tool_models import ToolModelError


@dataclass(frozen=True)
class RecognitionTaskSpec:
    """One immutable, versioned task contract for the 04 execution layer.

    A spec binds the task type, allowed targets, prompt, input/output
    contracts, crop policy, required outputs, structure-repair permission and
    write-back declarations into one versioned unit. It never accesses
    providers, filesystems, databases or environment variables.
    """

    task_type: RecognitionTaskType | str
    allowed_target_types: tuple[str, ...]
    required_context_types: tuple[str, ...] = ()
    prompt_template_id: str = ""
    prompt_version: str = ""
    input_contract_id: str = ""
    input_contract_version: str = ""
    output_schema_id: str = ""
    output_contract_version: str = ""
    crop_policy_id: str = ""
    preprocessing_version: str = "preprocess-v1"
    max_targets_per_request: int = 1
    required_outputs: tuple[str, ...] = ()
    allow_structure_repair: bool = False
    allowed_write_back: tuple[str, ...] = ("run", "payload")

    def __post_init__(self) -> None:
        object.__setattr__(self, "task_type", _coerce_task_type(self.task_type))
        object.__setattr__(
            self,
            "allowed_target_types",
            _read_unique_text_tuple(self.allowed_target_types, "allowed_target_types", allow_empty=False),
        )
        object.__setattr__(
            self,
            "required_context_types",
            _read_unique_text_tuple(self.required_context_types, "required_context_types", allow_empty=True),
        )
        object.__setattr__(
            self,
            "required_outputs",
            _read_unique_text_tuple(self.required_outputs, "required_outputs", allow_empty=False),
        )
        for field_name in (
            "prompt_template_id",
            "prompt_version",
            "input_contract_id",
            "input_contract_version",
            "output_schema_id",
            "output_contract_version",
            "crop_policy_id",
            "preprocessing_version",
        ):
            _require_text(getattr(self, field_name), field_name)
        if not isinstance(self.max_targets_per_request, int) or isinstance(self.max_targets_per_request, bool):
            raise ToolModelError("invalid_spec", "max_targets_per_request must be an integer")
        if self.max_targets_per_request < 1:
            raise ToolModelError("invalid_spec", "max_targets_per_request must be a positive integer")
        if not isinstance(self.allow_structure_repair, bool):
            raise ToolModelError("invalid_spec", "allow_structure_repair must be a boolean")
        object.__setattr__(
            self,
            "allowed_write_back",
            _read_unique_text_tuple(self.allowed_write_back, "allowed_write_back", allow_empty=False),
        )
        if "run" not in self.allowed_write_back or "payload" not in self.allowed_write_back:
            raise ToolModelError("invalid_spec", "allowed_write_back must include run and payload")


@dataclass(frozen=True)
class RecognitionTaskRegistry:
    """Immutable registry of recognition task specs with stable ordering."""

    specs: tuple[RecognitionTaskSpec, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.specs, tuple) or not all(
            isinstance(spec, RecognitionTaskSpec) for spec in self.specs
        ):
            raise ToolModelError("invalid_registry", "specs must be a tuple of RecognitionTaskSpec")
        seen: set[RecognitionTaskType] = set()
        for spec in self.specs:
            if spec.task_type in seen:
                raise ToolModelError("invalid_registry", "task registry must not contain duplicate task types")
            seen.add(spec.task_type)

    def get(self, task_type: RecognitionTaskType | str) -> RecognitionTaskSpec:
        """Return one registered spec or raise a classified not-found error."""

        wanted = _coerce_task_type(task_type)
        for spec in self.specs:
            if spec.task_type is wanted:
                return spec
        raise ToolModelError("NOT_FOUND", "recognition task spec was not found")

    def list_specs(self) -> tuple[RecognitionTaskSpec, ...]:
        """Return all specs in stable registration order."""

        return self.specs

    def validate_registry(self) -> None:
        """Validate registry-level integrity; raises on any violation."""

        if not self.specs:
            raise ToolModelError("invalid_registry", "task registry must contain at least one task spec")


def page_summary_spec() -> RecognitionTaskSpec:
    """Return the page_summary task contract.

    The task reads the whole page through a controlled resize, produces a
    summary plus key elements and uncertainties, and never declares a new
    graph node in this phase.
    """

    return RecognitionTaskSpec(
        task_type=RecognitionTaskType.PAGE_SUMMARY,
        allowed_target_types=("DrawingPage",),
        required_context_types=(),
        prompt_template_id="prompt/page-summary",
        prompt_version="prompt-v1",
        input_contract_id="input/page-summary",
        input_contract_version="1",
        output_schema_id="output/page-summary",
        output_contract_version="1",
        crop_policy_id="crop/page-summary-full-page-v1",
        preprocessing_version="preprocess-v1",
        max_targets_per_request=1,
        required_outputs=("summary", "key_elements", "uncertainties"),
        allow_structure_repair=False,
        allowed_write_back=("run", "payload"),
    )


def element_text_observation_spec() -> RecognitionTaskSpec:
    """Return the element_text_observation task contract.

    The task reads one text element's local crop and produces text
    observations; the only graph evidence it may write is TextObservation.
    """

    return RecognitionTaskSpec(
        task_type=RecognitionTaskType.ELEMENT_TEXT_OBSERVATION,
        allowed_target_types=("BlockCaption", "TableCaption", "PlainText", "Title", "DrawingAnnotation"),
        required_context_types=(),
        prompt_template_id="prompt/element-text-observation",
        prompt_version="prompt-v1",
        input_contract_id="input/element-text-observation",
        input_contract_version="1",
        output_schema_id="output/element-text-observation",
        output_contract_version="1",
        crop_policy_id="crop/element-text-local-v1",
        preprocessing_version="preprocess-v1",
        max_targets_per_request=1,
        required_outputs=("observations",),
        allow_structure_repair=False,
        allowed_write_back=("run", "payload", "TextObservation"),
    )


def block_semantic_identification_spec() -> RecognitionTaskSpec:
    """Return the block_semantic_identification task contract.

    The task reads one DrawingBlock local crop with a whitelisted minimum
    context and produces a block interpretation with optional observations.
    It must never modify ``DrawingBlock.block_type``.
    """

    return RecognitionTaskSpec(
        task_type=RecognitionTaskType.BLOCK_SEMANTIC_IDENTIFICATION,
        allowed_target_types=("DrawingBlock",),
        required_context_types=(),
        prompt_template_id="prompt/block-semantic-identification",
        prompt_version="prompt-v1",
        input_contract_id="input/block-semantic-identification",
        input_contract_version="1",
        output_schema_id="output/block-semantic-identification",
        output_contract_version="1",
        crop_policy_id="crop/block-local-min-context-v1",
        preprocessing_version="preprocess-v1",
        max_targets_per_request=1,
        required_outputs=("interpretation",),
        allow_structure_repair=True,
        allowed_write_back=("run", "payload", "BlockInterpretation", "TextObservation"),
    )


def basic_info_interpretation_spec() -> RecognitionTaskSpec:
    """Return the basic_info_interpretation task contract.

    The task reads one DrawingBasicInfo local crop and produces raw text,
    a summary and existing structured fields; it never introduces new source
    facts.
    """

    return RecognitionTaskSpec(
        task_type=RecognitionTaskType.BASIC_INFO_INTERPRETATION,
        allowed_target_types=("DrawingBasicInfo",),
        required_context_types=(),
        prompt_template_id="prompt/basic-info-interpretation",
        prompt_version="prompt-v1",
        input_contract_id="input/basic-info-interpretation",
        input_contract_version="1",
        output_schema_id="output/basic-info-interpretation",
        output_contract_version="1",
        crop_policy_id="crop/basic-info-local-v1",
        preprocessing_version="preprocess-v1",
        max_targets_per_request=1,
        required_outputs=("raw_text", "summary"),
        allow_structure_repair=False,
        allowed_write_back=("run", "payload", "BasicInfoInterpretation", "TextObservation"),
    )


def table_interpretation_spec() -> RecognitionTaskSpec:
    """Return the table_interpretation task contract.

    The task reads one Table local crop with a limited same-page TableCaption
    context and produces a summary, caption reference and uncertainties.
    """

    return RecognitionTaskSpec(
        task_type=RecognitionTaskType.TABLE_INTERPRETATION,
        allowed_target_types=("Table",),
        required_context_types=("TableCaption",),
        prompt_template_id="prompt/table-interpretation",
        prompt_version="prompt-v1",
        input_contract_id="input/table-interpretation",
        input_contract_version="1",
        output_schema_id="output/table-interpretation",
        output_contract_version="1",
        crop_policy_id="crop/table-local-caption-context-v1",
        preprocessing_version="preprocess-v1",
        max_targets_per_request=1,
        required_outputs=("summary", "caption_ref", "uncertainties"),
        allow_structure_repair=False,
        allowed_write_back=("run", "payload", "TableInterpretation"),
    )


def section_label_observation_spec() -> RecognitionTaskSpec:
    """Return the section_label_observation task contract.

    The task reads a CrossSection or BlockCaption local crop and returns raw
    and normalized label observations. Results may only be written as
    TextObservation; matching relations are never written by this task.
    """

    return RecognitionTaskSpec(
        task_type=RecognitionTaskType.SECTION_LABEL_OBSERVATION,
        allowed_target_types=("CrossSection", "BlockCaption"),
        required_context_types=(),
        prompt_template_id="prompt/section-label-observation",
        prompt_version="prompt-v1",
        input_contract_id="input/section-label-observation",
        input_contract_version="1",
        output_schema_id="output/section-label-observation",
        output_contract_version="1",
        crop_policy_id="crop/section-label-local-v1",
        preprocessing_version="preprocess-v1",
        max_targets_per_request=1,
        required_outputs=("raw_label", "normalized_label"),
        allow_structure_repair=False,
        allowed_write_back=("run", "payload", "TextObservation"),
    )


def relation_evidence_extraction_spec() -> RecognitionTaskSpec:
    """Return the relation_evidence_extraction task contract.

    The task reads one primary target crop with a limited same-page context
    whitelist and produces only candidate evidence plus supporting IDs. It
    never writes candidate or formal graph edges.
    """

    return RecognitionTaskSpec(
        task_type=RecognitionTaskType.RELATION_EVIDENCE_EXTRACTION,
        allowed_target_types=("DrawingBlock", "CrossSection", "Table"),
        required_context_types=(
            "DrawingBlock",
            "BlockCaption",
            "CrossSection",
            "TableCaption",
            "PlainText",
            "DrawingAnnotation",
            "Title",
        ),
        prompt_template_id="prompt/relation-evidence-extraction",
        prompt_version="prompt-v1",
        input_contract_id="input/relation-evidence-extraction",
        input_contract_version="1",
        output_schema_id="output/relation-evidence-extraction",
        output_contract_version="1",
        crop_policy_id="crop/relation-primary-local-context-v1",
        preprocessing_version="preprocess-v1",
        max_targets_per_request=1,
        required_outputs=("candidate_evidence", "supporting_ids"),
        allow_structure_repair=False,
        allowed_write_back=("run", "payload"),
    )


def build_default_task_registry() -> RecognitionTaskRegistry:
    """Build the first-version registry with all seven stable task specs."""

    return RecognitionTaskRegistry(
        specs=(
            page_summary_spec(),
            element_text_observation_spec(),
            block_semantic_identification_spec(),
            basic_info_interpretation_spec(),
            table_interpretation_spec(),
            section_label_observation_spec(),
            relation_evidence_extraction_spec(),
        )
    )


def _coerce_task_type(value: RecognitionTaskType | str) -> RecognitionTaskType:
    try:
        return value if isinstance(value, RecognitionTaskType) else RecognitionTaskType(value)
    except ValueError as exc:
        raise ToolModelError("invalid_task_type", "unsupported recognition task type") from exc


def _read_unique_text_tuple(values: Any, field_name: str, *, allow_empty: bool) -> tuple[str, ...]:
    if isinstance(values, (str, bytes)) or not isinstance(values, (list, tuple)):
        raise ToolModelError("invalid_sequence", f"{field_name} must be a sequence of strings")
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _require_text(value, field_name)
        if text in seen:
            raise ToolModelError("invalid_sequence", f"{field_name} must not contain duplicate values")
        seen.add(text)
        result.append(text)
    if not allow_empty and not result:
        raise ToolModelError("invalid_sequence", f"{field_name} must not be empty")
    return tuple(result)


def _require_text(value: Any, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")
    return value.strip()


__all__ = (
    "RecognitionTaskRegistry",
    "RecognitionTaskSpec",
    "basic_info_interpretation_spec",
    "block_semantic_identification_spec",
    "build_default_task_registry",
    "element_text_observation_spec",
    "page_summary_spec",
    "relation_evidence_extraction_spec",
    "section_label_observation_spec",
    "table_interpretation_spec",
)
