"""Real authenticated HTTP upload gate, with generated synthetic PDFs only."""

import json
import os
import time
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.db import engine
from app.private_io.repository import PrivateRepository
from app.private_io.storage import GCSObjectStorage
from tests.pdf_fixtures import metadata_for, pdf_bytes
from tests.test_auth_integration import login

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_UPLOAD_INTEGRATION") != "1",
    reason="Requires real local APIs, DB, Firebase and GCS",
)


def headers(email="student-a@example.test"):
    return {"Authorization": "Bearer " + login(email), "Idempotency-Key": str(uuid4())}


def upload(client, data, hdr, admin=False, **changes):
    metadata = metadata_for(data, **changes)
    if admin:
        metadata.pop("assessment_type")
        metadata.update(
            title="Synthetic reference",
            author="Synthetic author",
            publisher="Synthetic publisher",
            kind="reference",
            source_authority="supplemental",
            license_metadata={"rights": "synthetic"},
        )
    return client.post(
        "/v1/admin/knowledge/upload" if admin else "/v1/student/assessments/upload",
        headers=hdr,
        files={
            "file": ("synthetic.pdf", data, "application/pdf"),
            "metadata": (None, json.dumps(metadata)),
        },
    )


def cleanup(resource, principal):
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        document = session.execute(
            text(
                "SELECT document_id FROM student_data.assessments "
                "WHERE id=:id AND student_id=:owner"
            ),
            {"id": UUID(resource), "owner": repo.owner},
        ).scalar_one()
        record = repo.tombstone(document)
    GCSObjectStorage(Settings(), record.ref.owner_id).delete(record)


def test_student_upload_retry_owner_download_and_job():
    with httpx.Client(base_url="http://api:8000", timeout=30) as client:
        data, hdr = pdf_bytes(), headers()
        response = upload(client, data, hdr)
        assert response.status_code == 202, response.text
        accepted = response.json()
        assert set(accepted) == {"schema_version", "job_id", "resource_id", "status"}
        resource = accepted["resource_id"]
        repeated = upload(client, data, hdr)
        assert repeated.status_code == 202
        assert repeated.json()["resource_id"] == resource
        assert repeated.json()["job_id"] == accepted["job_id"]
        assert upload(client, pdf_bytes(pages=1), hdr, page_count=1).status_code == 409
        path = f"/v1/student/assessments/{resource}/file"
        assert client.get(path).status_code == 401
        assert client.get(path, headers=headers("student-b@example.test")).status_code == 404
        assert client.get(path, headers=headers("maintainer@example.test")).status_code == 403
        file = client.get(path, headers={**hdr, "X-Student-ID": str(uuid4()), "X-Role": "admin"})
        assert file.status_code == 200 and file.content == data
        assert file.headers["content-type"] == "application/pdf"
        assert file.headers["cache-control"] == "no-store"
        assert file.headers["x-content-type-options"] == "nosniff"
        assert file.headers["content-disposition"] == 'attachment; filename="document.pdf"'
        status_path = f"/v1/student/assessments/{resource}/status"
        assert client.get(status_path, headers=headers("student-b@example.test")).status_code == 404
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = client.get(status_path, headers=hdr).json()
            if status["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.3)
        assert status["status"] == "succeeded" and status["verified_state"] == "unverified"
        assert status["page_count"] == 2
        token = hdr["Authorization"].removeprefix("Bearer ")
        from app.auth.identity import verify_token

        cleanup(resource, verify_token(token))
        assert client.get(path, headers=hdr).status_code == 404
        assert upload(client, data, hdr).status_code == 409


def test_real_upload_rejections_leave_no_resources():
    with httpx.Client(base_url="http://api:8000", timeout=30) as client:
        hdr = headers()
        account = client.get("/v1/student/account", headers=hdr).json()["id"]
        with Session(engine()) as session, session.begin():
            from app.auth.identity import verify_token

            PrivateRepository(session, verify_token(hdr["Authorization"].split(" ")[1]))
            before = session.scalar(text("SELECT count(*) FROM student_data.documents"))
        for data, changes in [
            (b"html pretending to be pdf", {}),
            (pdf_bytes(), {"sha256": "0" * 64}),
            (pdf_bytes(active=True), {}),
            (pdf_bytes(), {"filename": "../secret.pdf"}),
            (pdf_bytes(), {"student_id": account}),
            (pdf_bytes(pages=201), {"page_count": 200}),
        ]:
            response = upload(client, data, hdr, **changes)
            assert response.status_code == 422, response.text
        too_large = client.post(
            "/v1/student/assessments/upload",
            content=b"x" * (26 * 1024 * 1024),
            headers={
                **hdr,
                "Content-Type": "multipart/form-data; boundary=x",
                "Content-Length": str(26 * 1024 * 1024),
            },
        )
        assert too_large.status_code == 413
        assert upload(client, pdf_bytes(), headers("maintainer@example.test")).status_code == 403
        assert (
            client.post(
                "/v1/student/assessments/upload",
                files={"file": ("synthetic.pdf", pdf_bytes(), "application/pdf")},
            ).status_code
            == 401
        )
        with Session(engine()) as session, session.begin():
            PrivateRepository(session, verify_token(hdr["Authorization"].split(" ")[1]))
            assert session.scalar(text("SELECT count(*) FROM student_data.documents")) == before


def test_maintainer_draft_upload_never_publishes_or_reads_students():
    with httpx.Client(base_url="http://admin-api:8000", timeout=30) as admin:
        data, hdr = pdf_bytes(), headers("maintainer@example.test")
        assert upload(admin, data, headers(), admin=True).status_code == 403
        response = upload(admin, data, hdr, admin=True)
        assert response.status_code == 202, response.text
        document = response.json()["resource_id"]
        assert upload(admin, data, hdr, admin=True).json()["resource_id"] == document
        path = f"/v1/admin/knowledge/{document}/file"
        assert admin.get(path).status_code == 401
        assert admin.get(path, headers=headers()).status_code == 403
        assert admin.get(path, headers=hdr).content == data
        status = admin.get(f"/v1/admin/knowledge/{document}/status", headers=hdr).json()
        assert status["document_id"] == document
        assert status["processing_kind"] == "storage_verification"
        import sqlalchemy

        admin_engine = sqlalchemy.create_engine(
            os.environ["ADMIN_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
        )
        from app.auth.identity import verify_token

        principal = verify_token(hdr["Authorization"].split(" ")[1])
        with Session(admin_engine) as session, session.begin():
            repo = PrivateRepository(session, principal)
            row = session.execute(
                text(
                    "SELECT status,created_by_admin_uid,source_authority "
                    "FROM global_knowledge.documents WHERE id=:id"
                ),
                {"id": UUID(document)},
            ).one()
            assert row == ("draft", principal.uid, "supplemental")
            record = repo.tombstone(UUID(document))
        with Session(engine()) as session:
            assert (
                session.scalar(
                    text("SELECT count(*) FROM published_knowledge.documents WHERE id=:id"),
                    {"id": UUID(document)},
                )
                == 0
            )
        GCSObjectStorage(Settings(service_mode="admin"), record.ref.owner_id).delete(record)
        admin_engine.dispose()
