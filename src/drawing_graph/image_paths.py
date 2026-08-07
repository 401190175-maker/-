"""Image-path normalization for JSON annotation pages."""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class ImagePathStatus(str, Enum):
    """Classified outcome for image-path normalization."""

    UNCHANGED = "unchanged"
    UPDATED = "updated"
    MISSING_IMAGE = "missing_image"


class ImagePathError(ValueError):
    """Raised when image-path normalization cannot safely continue."""

    def __init__(self, category: str, message: str):
        self.category = category
        super().__init__(message)


@dataclass(frozen=True)
class ImagePathIssue:
    """A categorized image-path issue for audit and import decisions."""

    category: str
    location: str
    message: str


@dataclass(frozen=True)
class ImagePathResult:
    """Result of checking or repairing one JSON document image path."""

    status: ImagePathStatus
    image_path: Path | None
    original_image_path: str | None
    issue: ImagePathIssue | None = None


def normalize_image_path(json_path: str | Path, document: dict[str, Any], data_root: str | Path) -> ImagePathResult:
    """Ensure JSON imagePath points to the same-directory same-stem PNG."""

    if not isinstance(document, dict):
        raise ImagePathError("invalid_document", "document must be a JSON object")

    json_file = Path(json_path).expanduser()
    root = Path(data_root).expanduser()
    root_resolved = root.resolve()
    _ensure_within_root(json_file, root_resolved)

    png_path = json_file.with_suffix(".png")
    _ensure_within_root(png_path, root_resolved)

    original_image_path = document.get("imagePath")
    if original_image_path is not None and not isinstance(original_image_path, str):
        raise ImagePathError("invalid_image_path", "imagePath must be a string")

    normalized_image_path = png_path.name
    if not png_path.exists():
        return ImagePathResult(
            status=ImagePathStatus.MISSING_IMAGE,
            image_path=None,
            original_image_path=original_image_path,
            issue=ImagePathIssue(
                category="same_name_png_missing",
                location=str(png_path),
                message=f"same-directory PNG is missing: {png_path.name}",
            ),
        )

    if original_image_path == normalized_image_path:
        return ImagePathResult(
            status=ImagePathStatus.UNCHANGED,
            image_path=png_path,
            original_image_path=original_image_path,
        )

    repaired_document = dict(document)
    repaired_document["imagePath"] = normalized_image_path
    _atomic_write_json(json_file, repaired_document)
    document["imagePath"] = normalized_image_path

    return ImagePathResult(
        status=ImagePathStatus.UPDATED,
        image_path=png_path,
        original_image_path=original_image_path,
    )


def _ensure_within_root(path: Path, root_resolved: Path) -> None:
    try:
        path.resolve().relative_to(root_resolved)
    except ValueError as error:
        raise ImagePathError("path_escapes_data_root", f"path escapes data_root: {path}") from error


def _atomic_write_json(json_path: Path, document: dict[str, Any]) -> None:
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=json_path.parent,
            prefix=f".{json_path.stem}-",
            suffix=".tmp",
            delete=False,
        ) as temp_file:
            json.dump(document, temp_file, ensure_ascii=False)
            temp_file.write("\n")
            temp_path = Path(temp_file.name)

        os.replace(temp_path, json_path)
    except OSError as error:
        if temp_path is not None and temp_path.exists():
            temp_path.unlink()
        raise ImagePathError("atomic_replace_failed", f"failed to atomically replace JSON: {json_path}") from error


__all__ = (
    "ImagePathError",
    "ImagePathIssue",
    "ImagePathResult",
    "ImagePathStatus",
    "normalize_image_path",
)
