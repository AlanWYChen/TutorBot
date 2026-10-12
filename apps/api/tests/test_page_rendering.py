from pathlib import Path

import pymupdf
import pytest

from app.assessments.rendering import render_to_directory
from app.domain.contracts import AssessmentUpload
from app.private_io.types import StorageError
from app.uploads.validation import validate_pdf
from tests.pdf_fixtures import metadata_for


def numbered_pdf(rotated=False, scanned=False):
    with pymupdf.open() as doc:
        for index in range(2):
            page = doc.new_page()
            if not scanned:
                page.insert_text((72, 90), f"{index * 2 + 1}. Solve x^2 - 4 = 0.")
                page.insert_text((72, 300), f"{index * 2 + 2}. Factor x^2 + 5x + 6.")
            if rotated:
                page.set_cropbox(pymupdf.Rect(30, 30, 560, 780))
                page.set_rotation(90)
        return doc.tobytes()


@pytest.mark.parametrize("rotated,scanned", [(False, False), (True, False), (False, True)])
def test_rendered_pages_and_candidate_coordinate_bounds(tmp_path: Path, rotated, scanned):
    data = numbered_pdf(rotated, scanned)
    result = render_to_directory(data, tmp_path)
    assert len(result.pages) == 2
    for page in result.pages:
        image = pymupdf.Pixmap(str(tmp_path / f"page-{page.page_number}.png"))
        assert (image.width, image.height) == (page.width, page.height)
        assert page.rotation == (90 if rotated else 0)
        assert len(page.candidates) == (0 if scanned else 2)
        for candidate in page.candidates:
            box = candidate.bbox
            assert 0 <= box.x < box.x + box.width <= page.width
            assert 0 <= box.y < box.y + box.height <= page.height


def test_render_limits_refuse_huge_page_without_allocation(tmp_path: Path):
    with pymupdf.open() as doc:
        doc.new_page(width=100000, height=100000)
        data = doc.tobytes()
    with pytest.raises(StorageError, match="render_limit_or_invalid_pdf"):
        render_to_directory(data, tmp_path)


def test_server_derives_page_count_for_browser_upload():
    data = numbered_pdf()
    metadata = metadata_for(data)
    metadata.pop("page_count")
    assert validate_pdf(data, AssessmentUpload(**metadata), "synthetic.pdf", "application/pdf") == 2


def test_native_render_retains_mark_annotations(tmp_path: Path):
    with pymupdf.open() as doc:
        page = doc.new_page()
        page.insert_text((72, 90), "1. Solve x^2 - 4 = 0.")
        mark = page.add_rect_annot(pymupdf.Rect(70, 70, 180, 120))
        mark.set_colors(stroke=(1, 0, 0))
        mark.set_border(width=4)
        mark.update()
        data = doc.tobytes()
    render_to_directory(data, tmp_path)
    image = pymupdf.Pixmap(str(tmp_path / "page-1.png"))
    pixels = image.samples
    assert any(
        r > 180 and g < 70 and b < 70
        for r, g, b in zip(pixels[::3], pixels[1::3], pixels[2::3], strict=True)
    )
