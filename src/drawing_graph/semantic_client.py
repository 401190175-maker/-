"""Multimodal recognition client protocol and test fake."""

from __future__ import annotations

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Mapping, Protocol

from .tool_models import BBox, SemanticTargetInput, ToolModelError


TargetRef = tuple[str, str, BBox, BBox]


@dataclass(frozen=True)
class RecognitionClientRequest:
    """Recognition input for one page/element image region.

    The request carries the image reference, target bboxes, a fixed model
    profile and prompt version, and minimal page context. It must never
    accept provider credentials as free text.
    """

    page_id: str
    image_path: str
    targets: tuple[TargetRef, ...]
    model_profile: str
    prompt_version: str
    target_inputs: tuple[SemanticTargetInput, ...] = ()
    context: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for field_name in ("page_id", "image_path", "model_profile", "prompt_version"):
            _require_text(getattr(self, field_name), field_name)
        if not isinstance(self.targets, tuple):
            raise ToolModelError("invalid_targets", "targets must be a tuple")
        for target in self.targets:
            if not isinstance(target, tuple) or len(target) != 4:
                raise ToolModelError("invalid_targets", "each target must contain id, type, bbox, normalized_bbox")
            _require_text(target[0], "target_element_id")
            _require_text(target[1], "target_element_type")
            if not isinstance(target[2], BBox) or not isinstance(target[3], BBox):
                raise ToolModelError("invalid_targets", "target bboxes must be BBox instances")
        if not isinstance(self.target_inputs, tuple) or not all(
            isinstance(item, SemanticTargetInput)
            for item in self.target_inputs
        ):
            raise ToolModelError(
                "invalid_target_inputs",
                "target_inputs must be a tuple of SemanticTargetInput",
            )
        if not isinstance(self.context, Mapping):
            raise ToolModelError("invalid_context", "context must be a mapping")
        forbidden = {"api_key", "token", "password", "secret"}
        if forbidden.intersection(str(key).lower() for key in self.context):
            raise ToolModelError("invalid_context", "context must not contain provider credentials")
        object.__setattr__(self, "context", MappingProxyType(dict(self.context)))


@dataclass(frozen=True)
class RecognitionClientResult:
    status: str
    observations: tuple[Mapping[str, Any], ...] = ()
    interpretations: tuple[Mapping[str, Any], ...] = ()
    error_code: str | None = None
    error_message: str | None = None
    model_name: str | None = None
    model_version: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"succeeded", "partial", "failed"}:
            raise ToolModelError("invalid_recognition_status", "recognition status is not supported")
        object.__setattr__(self, "observations", tuple(MappingProxyType(dict(item)) for item in self.observations))
        object.__setattr__(
            self,
            "interpretations",
            tuple(MappingProxyType(dict(item)) for item in self.interpretations),
        )


class MultimodalRecognitionClient(Protocol):
    """Protocol for page/element recognition clients."""

    def recognize(self, request: RecognitionClientRequest) -> RecognitionClientResult:
        """Return classified recognition output for a page request."""


class FakeMultimodalRecognitionClient:
    """Configurable fake client for unit tests."""

    def __init__(
        self,
        outputs: list[Mapping[str, Any]] | None = None,
        interpretations: list[Mapping[str, Any]] | None = None,
        status: str = "succeeded",
        unparseable: bool = False,
        timeout: bool = False,
        model_name: str = "fake-multimodal",
        model_version: str = "fake-v1",
    ):
        self.outputs = tuple(outputs or ())
        self.interpretations = tuple(interpretations or ())
        self.status = status
        self.unparseable = unparseable
        self.timeout = timeout
        self.model_name = model_name
        self.model_version = model_version
        self.requests: list[RecognitionClientRequest] = []

    def recognize(self, request: RecognitionClientRequest) -> RecognitionClientResult:
        self.requests.append(request)
        if self.timeout:
            raise ToolModelError("RECOGNITION_FAILED", "recognition client timed out")
        if self.unparseable:
            raise ToolModelError("RECOGNITION_FAILED", "recognition client returned unparseable output")
        return RecognitionClientResult(
            status=self.status,
            observations=self.outputs,
            interpretations=self.interpretations,
            error_code="recognition_failed" if self.status == "failed" else None,
            error_message="fake recognition failed" if self.status == "failed" else None,
            model_name=self.model_name,
            model_version=self.model_version,
        )


def _require_text(value: Any, field_name: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ToolModelError("missing_required_field", f"{field_name} must be a non-empty string")


__all__ = (
    "FakeMultimodalRecognitionClient",
    "MultimodalRecognitionClient",
    "RecognitionClientRequest",
    "RecognitionClientResult",
    "TargetRef",
)
