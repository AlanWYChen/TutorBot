import subprocess
import sys
from uuid import uuid4

import pymupdf
import pytest
from pydantic import ValidationError

from app.studio.types import AnnotationCreate


def payload(**changes):
    return {
        "client_annotation_id": str(uuid4()),
        "question": "Synthetic question",
        "page_number": 1,
        "bbox": {"x": 10, "y": 20, "width": 100, "height": 50},
        **changes,
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"marks_awarded": 5, "marks_possible": 4},
        {"marks_awarded": float("nan")},
        {"marks_awarded": True},
        {"observed_behaviours": "notation visible"},
        {"observation_status": "observed"},
        {"intervention": "check a step"},
        {"student_id": str(uuid4())},
        {"bbox": {"x": -1, "y": 0, "width": 10, "height": 10}},
        {"status": "published"},
    ],
)
def test_annotation_evidence_and_scope_validation(changes):
    with pytest.raises(ValidationError):
        AnnotationCreate.model_validate(payload(**changes))


def test_pixel_crop_matches_selected_area():
    image = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 200, 100), False)
    image.clear_with(255)
    result = subprocess.run(
        [sys.executable, "-m", "app.studio.crop_image", "10", "20", "100", "50"],
        input=image.tobytes("png"),
        capture_output=True,
        check=True,
        timeout=10,
        env={"PYTHONDONTWRITEBYTECODE": "1"},
    )
    cropped = pymupdf.Pixmap(result.stdout)
    assert (cropped.width, cropped.height) == (100, 50)
    assert cropped.samples == b"\xff" * (100 * 50 * 3)
