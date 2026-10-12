"""Credential-free native rendering subprocess; only generated page files are written."""

import json
import math
import re
import resource
import sys
from pathlib import Path
from typing import Any


def main() -> None:
    resource.setrlimit(resource.RLIMIT_AS, (768 * 1024 * 1024, 768 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CPU, (50, 50))
    resource.setrlimit(resource.RLIMIT_FSIZE, (25 * 1024 * 1024, 25 * 1024 * 1024))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    import pymupdf as native

    pymupdf: Any = native

    from app.assessments.types import RENDER_SCALE
    from app.limits import MAX_DOCUMENT_PAGES, MAX_UPLOAD_BYTES

    pymupdf.TOOLS.mupdf_display_errors(False)
    pymupdf.TOOLS.mupdf_display_warnings(False)
    output = Path(sys.argv[1])
    data = sys.stdin.buffer.read(MAX_UPLOAD_BYTES + 1)
    pages: list[dict[str, object]] = []
    total_bytes = 0
    try:
        with pymupdf.open(stream=data, filetype="pdf") as doc:
            if doc.is_encrypted or not 1 <= doc.page_count <= MAX_DOCUMENT_PAGES:
                raise ValueError
            for index, page in enumerate(doc):
                width = math.ceil(page.rect.width * RENDER_SCALE)
                height = math.ceil(page.rect.height * RENDER_SCALE)
                if width <= 0 or height <= 0 or width * height > 8_000_000:
                    raise ValueError
                pix = page.get_pixmap(
                    matrix=pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE), alpha=False, annots=True
                )
                image = pix.tobytes("png")
                total_bytes += len(image)
                if len(image) > MAX_UPLOAD_BYTES or total_bytes > 128 * 1024 * 1024:
                    raise ValueError
                (output / f"page-{index + 1}.png").write_bytes(image)
                candidates: list[dict[str, object]] = []
                # Native text is used only for numbered prompt navigation, never grading.
                # Rotated/cropped page text is transformed into the canonical image pixels.
                text = page.get_text("dict")
                for block in text.get("blocks", []):
                    for line in block.get("lines", []):
                        words = "".join(span.get("text", "") for span in line.get("spans", []))
                        match = re.match(
                            r"^\s*(?:Question\s+)?([1-9]\d{0,2})[.):]\s+", words, re.IGNORECASE
                        )
                        if not match or len(candidates) >= 100:
                            continue
                        rect = (
                            pymupdf.Rect(line["bbox"])
                            * page.rotation_matrix
                            * pymupdf.Matrix(RENDER_SCALE, RENDER_SCALE)
                        )
                        x, y = max(0, rect.x0 - pix.x), max(0, rect.y0 - pix.y)
                        right, bottom = (
                            min(pix.width, rect.x1 - pix.x),
                            min(pix.height, rect.y1 - pix.y),
                        )
                        if right > x and bottom > y:
                            candidates.append(
                                {
                                    "number": int(match[1]),
                                    "bbox": {
                                        "x": x,
                                        "y": y,
                                        "width": right - x,
                                        "height": bottom - y,
                                    },
                                }
                            )
                pages.append(
                    {
                        "page_number": index + 1,
                        "width": pix.width,
                        "height": pix.height,
                        "rotation": page.rotation,
                        "candidates": candidates,
                    }
                )
        print(json.dumps({"pages": pages}))
    except Exception:
        print('{"error":"render_limit_or_invalid_pdf"}')


if __name__ == "__main__":
    main()
