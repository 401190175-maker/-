"""Offline contract tests for in-memory region image preprocessing."""

from __future__ import annotations

import hashlib
import shutil
import unittest
import uuid
from contextlib import contextmanager
from pathlib import Path

from PIL import Image

from drawing_graph.recognition_image_preprocessing import (
    PreparedRecognitionImage,
    RecognitionImageError,
    RegionImagePreprocessor,
)
from drawing_graph.recognition_models import (
    RecognitionExecutionRequest,
    RecognitionImageRole,
    RecognitionTaskType,
    ValidatedRecognitionRequest,
)
from drawing_graph.recognition_tasks import (
    block_semantic_identification_spec,
    element_text_observation_spec,
    page_summary_spec,
)
from drawing_graph.tool_models import BBox, SemanticTargetInput


def _write_png(path: Path, size: tuple[int, int] = (100, 80)) -> None:
    Image.new("RGB", size, "white").save(path, format="PNG")


@contextmanager
def _fixture_dir():
    base = Path(__file__).resolve().parents[1] / ".superpowers" / "sdd" / "tasks" / "image-fixtures"
    path = base / f"case-{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def _target(
    *,
    target_id: str = "target-1",
    target_type: str = "DrawingBlock",
    task_type: str = "block_semantic_identification",
    target_element_id: str = "block-1",
    bbox: BBox = BBox(10, 10, 50, 40),
) -> SemanticTargetInput:
    return SemanticTargetInput(
        target_id=target_id,
        page_id="page-1",
        target_type=target_type,
        task_type=task_type,
        target_element_id=target_element_id,
        bbox=bbox,
        normalized_bbox=BBox(0.1, 0.125, 0.5, 0.5),
    )


def _validated_request(
    image_path: str,
    *,
    task_type: str = "block_semantic_identification",
    targets: tuple[SemanticTargetInput, ...] | None = None,
    image_size: tuple[int, int] = (100, 80),
) -> ValidatedRecognitionRequest:
    return ValidatedRecognitionRequest(
        request_id="req-1",
        recognition_run_id="run-1",
        page_id="page-1",
        task_type=RecognitionTaskType(task_type),
        targets=targets or (_target(),),
        model_profile="default",
        prompt_version="prompt-v1",
        input_contract_version="1",
        output_contract_version="1",
        preprocessing_version="preprocess-v1",
        write_back=False,
        deadline_seconds=60.0,
        image_path=image_path,
        image_size=image_size,
    )


class RegionCropTests(unittest.TestCase):
    """Local bbox crops must stay in memory with auditable metadata."""

    def test_local_crop_produces_in_memory_prepared_image(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            prepared = RegionImagePreprocessor().prepare(
                _validated_request(str(source)),
                block_semantic_identification_spec(),
            )
            self.assertEqual(1, len(prepared))
            image = prepared[0]
            self.assertIs(RecognitionImageRole.TARGET, image.role)
            self.assertEqual("image/png", image.mime)
            self.assertTrue(image.content.startswith(b"\x89PNG"))
            self.assertEqual((62, 52), image.output_size)
            self.assertEqual(1.0, image.scale)
            self.assertEqual("preprocess-v1", image.preprocessing_version)
            self.assertEqual(64, len(image.source_hash))
            self.assertEqual(64, len(image.prepared_hash))
            self.assertEqual(hashlib.sha256(image.content).hexdigest(), image.prepared_hash)

    def test_padding_uses_task_crop_policy(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            prepared = RegionImagePreprocessor().prepare(
                _validated_request(str(source)),
                block_semantic_identification_spec(),
            )
            image = prepared[0]
            self.assertEqual(BBox(0, 0, 62, 52), image.crop_bbox)
            self.assertEqual(12, image.padding)

    def test_padding_is_clamped_to_image_bounds(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            target = _target(bbox=BBox(0, 0, 10, 10))
            request = _validated_request(
                str(source),
                targets=(target,),
            )
            image = RegionImagePreprocessor().prepare(request, block_semantic_identification_spec())[0]
            self.assertEqual(BBox(0, 0, 22, 22), image.crop_bbox)

    def test_element_text_task_uses_its_own_padding(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            target = _target(
                target_type="BlockCaption",
                task_type="element_text_observation",
                target_element_id="caption-1",
                bbox=BBox(20, 20, 60, 40),
            )
            request = _validated_request(
                str(source),
                task_type="element_text_observation",
                targets=(target,),
            )
            image = RegionImagePreprocessor().prepare(request, element_text_observation_spec())[0]
            self.assertEqual(BBox(12, 12, 68, 48), image.crop_bbox)

    def test_page_summary_uses_full_page_role(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            target = SemanticTargetInput(
                target_id="target-page",
                page_id="page-1",
                target_type="DrawingPage",
                task_type="page_summary",
            )
            request = _validated_request(
                str(source),
                task_type="page_summary",
                targets=(target,),
            )
            image = RegionImagePreprocessor().prepare(request, page_summary_spec())[0]
            self.assertIs(RecognitionImageRole.PAGE, image.role)
            self.assertEqual(BBox(0, 0, 100, 80), image.crop_bbox)
            self.assertEqual((100, 80), image.output_size)

    def test_repr_does_not_expose_bytes(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            image = RegionImagePreprocessor().prepare(
                _validated_request(str(source)),
                block_semantic_identification_spec(),
            )[0]
            rendered = repr(image)
            self.assertNotIn("PNG", rendered)
            self.assertNotIn("content=", rendered)
            self.assertNotIn("b'\\x89", rendered)

    def test_no_crop_file_is_created(self) -> None:
        with _fixture_dir() as tmp:
            source = Path(tmp) / "page-1.png"
            _write_png(source)
            RegionImagePreprocessor().prepare(
                _validated_request(str(source)),
                block_semantic_identification_spec(),
            )
            self.assertEqual(["page-1.png"], [item.name for item in Path(tmp).iterdir()])

    def test_missing_source_image_raises_recognition_image_error(self) -> None:
        with _fixture_dir() as tmp:
            missing = Path(tmp) / "missing.png"
            with self.assertRaises(RecognitionImageError):
                RegionImagePreprocessor().prepare(
                    _validated_request(str(missing)),
                    block_semantic_identification_spec(),
                )

    def test_requirements_pin_pillow_without_ocr_engines(self) -> None:
        requirements = (Path(__file__).resolve().parents[1] / "requirements.txt").read_text(encoding="utf-8")
        self.assertIn("Pillow>=10,<13", requirements)
        self.assertNotIn("opencv", requirements.lower())
        self.assertNotIn("tesseract", requirements.lower())
        self.assertNotIn("paddleocr", requirements.lower())

    def test_preprocessor_module_is_pure(self) -> None:
        import drawing_graph.recognition_image_preprocessing as module

        source = Path(module.__file__).read_text(encoding="utf-8")
        import_lines = "\n".join(
            line.strip().lower()
            for line in source.splitlines()
            if line.strip().startswith(("import ", "from "))
        )
        for forbidden in ("neo4j", "repository", "cypher", "httpx", "qwen", "facade", "os.environ", "pathlib"):
            self.assertNotIn(forbidden, import_lines)


if __name__ == "__main__":
    unittest.main()
