"""Data-root scanner for drawing set directories and JSON annotation files."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ScannerError(ValueError):
    """Raised when the data root or discovered paths are invalid."""


@dataclass(frozen=True)
class JsonAnnotationFile:
    """A JSON annotation file and its same-directory PNG candidate."""

    path: Path
    image_path: Path | None


@dataclass(frozen=True)
class DrawingSetScan:
    """A drawing set directory with its sorted JSON annotation files."""

    name: str
    path: Path
    json_files: tuple[JsonAnnotationFile, ...]


def scan_drawing_sets(data_root: str | Path) -> tuple[DrawingSetScan, ...]:
    """Return drawing set directories and JSON files in deterministic name order."""

    root = Path(data_root).expanduser()
    if not root.exists():
        raise ScannerError(f"data_root does not exist: {root}")
    if not root.is_dir():
        raise ScannerError(f"data_root must be a directory: {root}")

    root_resolved = root.resolve()
    drawing_sets = []
    for drawing_set_dir in sorted(
        (path for path in root.iterdir() if path.is_dir()),
        key=lambda path: path.name,
    ):
        _ensure_within_root(drawing_set_dir, root_resolved)
        json_files = tuple(
            _scan_json_file(json_path, root_resolved)
            for json_path in sorted(drawing_set_dir.glob("*.json"), key=lambda path: path.name)
        )
        drawing_sets.append(
            DrawingSetScan(
                name=drawing_set_dir.name,
                path=drawing_set_dir,
                json_files=json_files,
            )
        )

    return tuple(drawing_sets)


def _scan_json_file(json_path: Path, root_resolved: Path) -> JsonAnnotationFile:
    _ensure_within_root(json_path, root_resolved)
    png_path = json_path.with_suffix(".png")
    if png_path.exists():
        _ensure_within_root(png_path, root_resolved)
        return JsonAnnotationFile(path=json_path, image_path=png_path)
    return JsonAnnotationFile(path=json_path, image_path=None)


def _ensure_within_root(path: Path, root_resolved: Path) -> None:
    try:
        path.resolve().relative_to(root_resolved)
    except ValueError as error:
        raise ScannerError(f"path escapes data_root: {path}") from error
