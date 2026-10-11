from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth.identity import Principal, current_principal
from app.domain.contracts import AssessmentUpload, JobAccepted, JobState
from app.limits import MAX_UPLOAD_BYTES
from app.uploads.routes import student_uploads
from app.uploads.validation import UploadRejected, validate_pdf
from tests.pdf_fixtures import metadata_for, pdf_bytes


def test_valid_pdf_inspection_and_metadata() -> None:
    data = pdf_bytes()
    assert (
        validate_pdf(
            data, AssessmentUpload(**metadata_for(data)), "synthetic.pdf", "application/pdf"
        )
        == 2
    )


@pytest.mark.parametrize(
    "kind,code",
    [
        ("html", "invalid_document"),
        ("broken", "invalid_document"),
        ("trailing", "invalid_document"),
        ("encrypted", "encrypted_document"),
        ("active", "unsupported_pdf_features"),
        ("attachment", "unsupported_pdf_features"),
        ("pages", "page_limit"),
        ("count", "upload_metadata_mismatch"),
        ("digest", "upload_metadata_mismatch"),
        ("size", "upload_metadata_mismatch"),
        ("extension", "pdf_required"),
        ("mime", "pdf_required"),
        ("oversize", "file_size_limit"),
    ],
)
def test_binary_safeguards(kind, code):
    data = pdf_bytes()
    changes, filename, mime = {}, "synthetic.pdf", "application/pdf"
    if kind == "html":
        data = b"<html>synthetic spoof</html>"
    elif kind == "broken":
        data = b"%PDF-1.7\nsynthetic invalid structure\n%%EOF"
    elif kind == "trailing":
        data += b"<script>synthetic</script>"
    elif kind in {"encrypted", "active", "attachment"}:
        data = pdf_bytes(**{kind: True})
    elif kind == "pages":
        data = pdf_bytes(pages=201)
        changes["page_count"] = 200
    elif kind == "count":
        changes["page_count"] = 1
    elif kind == "digest":
        changes["sha256"] = "0" * 64
    elif kind == "size":
        changes["size_bytes"] = 1
    elif kind == "extension":
        filename = "synthetic.exe"
        changes["filename"] = filename
    elif kind == "mime":
        mime = "text/html"
    elif kind == "oversize":
        data = b"x" * (MAX_UPLOAD_BYTES + 1)
    meta = metadata_for(data, **changes)
    if kind == "oversize":
        meta["size_bytes"] = MAX_UPLOAD_BYTES
    with pytest.raises(UploadRejected, match=code):
        validate_pdf(data, AssessmentUpload(**meta), filename, mime)


def client_for(monkeypatch, role="student"):
    app = FastAPI()
    app.include_router(student_uploads)
    app.dependency_overrides[current_principal] = lambda: Principal(uid="synthetic", role=role)
    saved = []

    def save(*args):
        saved.append(args)
        return JobAccepted(job_id=uuid4(), resource_id=uuid4(), status=JobState.QUEUED)

    monkeypatch.setattr("app.uploads.routes.save_upload", save)
    return TestClient(app), saved


def parts(data, **changes):
    import json

    return {
        "metadata": (None, json.dumps(metadata_for(data, **changes))),
        "file": ("synthetic.pdf", data, "application/pdf"),
    }


def test_http_upload_and_authorization_before_body(monkeypatch):
    client, saved = client_for(monkeypatch)
    data = pdf_bytes()
    response = client.post(
        "/v1/student/assessments/upload",
        files=parts(data),
        headers={"Idempotency-Key": str(uuid4())},
    )
    assert response.status_code == 202
    assert len(saved) == 1 and saved[0][0].uid == "synthetic"
    admin, saved = client_for(monkeypatch, "admin")
    response = admin.post(
        "/v1/student/assessments/upload",
        content=b"unparsed synthetic",
        headers={"Content-Type": "multipart/form-data"},
    )
    assert response.status_code == 403 and not saved


def test_http_rejects_spoofing_scope_fields_and_extra_parts(monkeypatch):
    client, saved = client_for(monkeypatch)
    for data, changes in [
        (b"html masquerading as pdf", {}),
        (pdf_bytes(), {"student_id": str(uuid4())}),
    ]:
        response = client.post(
            "/v1/student/assessments/upload",
            files=parts(data, **changes),
            headers={"Idempotency-Key": str(uuid4())},
        )
        assert response.status_code == 422
    files = parts(pdf_bytes())
    files["extra"] = (None, "forged-scope")
    assert (
        client.post(
            "/v1/student/assessments/upload", files=files, headers={"Idempotency-Key": str(uuid4())}
        ).status_code
        == 400
    )
    assert not saved


def test_http_body_limits_declared_and_chunked(monkeypatch):
    client, saved = client_for(monkeypatch)
    headers = {
        "Content-Type": "multipart/form-data; boundary=synthetic",
        "Idempotency-Key": str(uuid4()),
    }
    response = client.post(
        "/v1/student/assessments/upload",
        content=b"small",
        headers={**headers, "Content-Length": str(MAX_UPLOAD_BYTES + 100000)},
    )
    assert response.status_code == 413
    monkeypatch.setattr("app.uploads.routes.MAX_MULTIPART_BYTES", 1024)
    body = (
        b'--synthetic\r\nContent-Disposition: form-data; name="file"; filename="test.pdf"\r\n'
        b"Content-Type: application/pdf\r\n\r\n" + b"x" * 2000 + b"\r\n--synthetic--\r\n"
    )
    response = client.post(
        "/v1/student/assessments/upload", content=iter([body[:300], body[300:]]), headers=headers
    )
    assert response.status_code == 413
    assert not saved


def test_native_timeout_is_sanitized_and_has_no_service_secrets(monkeypatch):
    import subprocess

    seen = []

    def timeout(*args, **kwargs):
        seen.append(kwargs)
        raise subprocess.TimeoutExpired("SENSITIVE", 10)

    monkeypatch.setattr("app.uploads.validation.subprocess.run", timeout)
    data = pdf_bytes()
    with pytest.raises(UploadRejected, match="^invalid_document$"):
        validate_pdf(
            data, AssessmentUpload(**metadata_for(data)), "synthetic.pdf", "application/pdf"
        )
    assert seen[0]["env"] == {"PYTHONDONTWRITEBYTECODE": "1", "PYTHONUNBUFFERED": "1"}
    assert seen[0]["timeout"] == 10


def test_interrupted_or_idle_upload_closes_with_safe_error(monkeypatch):
    import asyncio

    from fastapi import HTTPException, Request

    from app.uploads.routes import receive_upload

    for interrupted in (True, False):

        async def receive(interrupted=interrupted):
            if interrupted:
                return {"type": "http.disconnect"}
            raise TimeoutError("SENSITIVE")

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/upload",
                "app": FastAPI(),
                "headers": [(b"content-type", b"multipart/form-data; boundary=x")],
            },
            receive=receive,
        )
        with pytest.raises(HTTPException) as exc:
            asyncio.run(
                receive_upload(request, Principal(uid="synthetic", role="student"), str(uuid4()))
            )
        assert exc.value.status_code == (400 if interrupted else 408)
        assert "SENSITIVE" not in str(exc.value.detail)
