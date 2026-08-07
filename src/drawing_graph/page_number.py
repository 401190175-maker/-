"""Page-number parsing for drawing annotation file names."""

from __future__ import annotations

import re
from pathlib import Path


PAGE_FILE_PATTERN = re.compile(r"^road_(\d+)\.json$")


class PageNumberError(ValueError):
    """Raised when a JSON file name cannot produce a classified page number."""

    def __init__(self, file_name: str):
        self.category = "invalid_page_filename"
        super().__init__(f"page file name must match road_<number>.json: {file_name}")


def parse_page_number(json_path: str | Path) -> int:
    """Return the page number from a file name matching road_<number>.json exactly."""

    file_name = Path(json_path).name
    match = PAGE_FILE_PATTERN.fullmatch(file_name)
    if match is None:
        raise PageNumberError(file_name)

    return int(match.group(1))


__all__ = ("PageNumberError", "parse_page_number")
