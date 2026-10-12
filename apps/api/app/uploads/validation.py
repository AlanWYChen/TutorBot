import hashlib
import re
import subprocess
import sys

from pydantic import BaseModel, ConfigDict, Field

from app.domain.contracts import UploadMetadata
from app.limits import MAX_DOCUMENT_PAGES, MAX_UPLOAD_BYTES


class UploadRejected(Exception):
    def __init__(self, code: str, status: int = 422):
        self.code, self.status = code, status
        super().__init__(code)


class PDFInspection(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_count: int = Field(ge=1, le=MAX_DOCUMENT_PAGES)


def validate_pdf(data: bytes, metadata: UploadMetadata, filename: str, media_type: str) -> int:
    if not 0 < len(data) <= MAX_UPLOAD_BYTES:
        raise UploadRejected("file_size_limit", 413)
    # Treat extension, declared type and signature as independent checks.
    if (
        metadata.media_type != "application/pdf"
        or media_type != "application/pdf"
        or not filename.lower().endswith(".pdf")
        or filename != metadata.filename
    ):
        raise UploadRejected("pdf_required", 415)
    if metadata.size_bytes != len(data) or metadata.sha256 != hashlib.sha256(data).hexdigest():
        raise UploadRejected("upload_metadata_mismatch")
    if not re.match(rb"%PDF-(?:1\.[0-7]|2\.0)(?:\r|\n)", data[:16]):
        raise UploadRejected("invalid_document")
    if not data.rstrip(b" \t\r\n\x00").endswith(b"%%EOF"):
        raise UploadRejected("invalid_document")
    try:
        # No credentials are inherited. No native parser runs inside the API process.
        result = subprocess.run(
            [sys.executable, "-m", "app.uploads.inspect_pdf"],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            env={"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"},
            check=True,
        )
        if len(result.stdout) > 1024:
            raise ValueError("oversized inspection result")
        import json

        payload = json.loads(result.stdout)
        errors = {
            "invalid_document",
            "encrypted_document",
            "page_limit",
            "unsupported_pdf_features",
        }
        if payload.get("error") in errors:
            raise UploadRejected(payload["error"])
        inspection = PDFInspection.model_validate(payload)
    except UploadRejected:
        raise
    except Exception:
        raise UploadRejected("invalid_document") from None
    if metadata.page_count is not None and inspection.page_count != metadata.page_count:
        raise UploadRejected("upload_metadata_mismatch")
    return inspection.page_count
