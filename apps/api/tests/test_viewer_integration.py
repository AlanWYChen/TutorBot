"""Synthetic multi-page viewer gate against web proxy, APIs and real workers."""

import json
import os
import time
from uuid import UUID

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.identity import verify_token
from app.config import Settings
from app.db import engine
from app.private_io.repository import PrivateRepository
from app.private_io.storage import GCSObjectStorage
from app.private_io.types import StoredObject
from tests.pdf_fixtures import metadata_for
from tests.test_auth_integration import login
from tests.test_page_rendering import numbered_pdf
from tests.test_upload_integration import headers

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_VIEWER_INTEGRATION") != "1",
    reason="Requires web, APIs, Firebase, DB, GCS and worker",
)


def test_multi_page_viewer_private_proxy_and_duplicate_render():
    data = numbered_pdf(rotated=True)
    hdr = headers()
    metadata = metadata_for(data)
    metadata.pop("page_count")
    with httpx.Client(base_url="http://web:3000", timeout=60) as web:
        response = web.post(
            "/api/assessments/upload",
            headers=hdr,
            files={
                "file": ("synthetic.pdf", data, "application/pdf"),
                "metadata": (None, json.dumps(metadata)),
            },
        )
        assert response.status_code == 202, response.text
        resource = response.json()["resource_id"]
        endpoint = f"/api/assessments/{resource}"
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            response = web.get(endpoint + "/pages", headers=hdr)
            assert response.status_code == 200, response.text
            pages = response.json()["pages"]
            if pages:
                break
            time.sleep(0.3)
        assert len(pages) == 2
        assert sum(len(p["candidates"]) for p in pages) == 4
        assert all(page["rotation"] == 90 for page in pages)
        assert [[candidate["label"] for candidate in page["candidates"]] for page in pages] == [
            ["Possible question 1", "Possible question 2"],
            ["Possible question 3", "Possible question 4"],
        ]
        other = {"Authorization": "Bearer " + login("student-b@example.test")}
        for suffix in ["/pages", "/pages/1/image", "/render"]:
            method = web.post if suffix == "/render" else web.get
            assert method(endpoint + suffix, headers=other).status_code == 404
            assert method(endpoint + suffix).status_code == 401
        admin = {"Authorization": "Bearer " + login("maintainer@example.test")}
        assert web.get(endpoint + "/pages/1/image", headers=admin).status_code == 403
        image = web.get(endpoint + "/pages/2/image", headers=hdr)
        assert image.status_code == 200 and image.content.startswith(b"\x89PNG\r\n\x1a\n")
        assert image.headers["cache-control"] == "no-store"
        assert web.get(endpoint + "/pages/3/image", headers=hdr).status_code == 404
        original = web.get(endpoint + "/file", headers=hdr)
        assert original.content == data
        first = web.post(endpoint + "/render", headers=hdr).json()
        second = web.post(endpoint + "/render", headers=hdr).json()
        assert first["job_id"] == second["job_id"]
        assert web.get(endpoint + "/pages", headers=hdr).json()["pages"] == pages
        items = web.get("/api/assessments", headers=hdr).json()["assessments"]
        assert any(item["id"] == resource for item in items)
        assert not any(
            item["id"] == resource
            for item in web.get("/api/assessments", headers=other).json()["assessments"]
        )
        principal = verify_token(hdr["Authorization"].split(" ")[1])
        with Session(engine()) as session, session.begin():
            repo = PrivateRepository(session, principal)
            document = session.scalar(
                text(
                    "SELECT document_id FROM student_data.assessments "
                    "WHERE id=:id AND student_id=:owner"
                ),
                {"id": UUID(resource), "owner": repo.owner},
            )
            source = repo.object(document)
            records = [
                StoredObject.model_validate(row)
                for row in session.execute(
                    text(
                        "SELECT record FROM student_data.storage_objects WHERE student_id=:owner "
                        "AND record->'ref'->>'assessment_id'=:id AND deleted_at IS NULL"
                    ),
                    {"owner": repo.owner, "id": resource},
                ).scalars()
            ]
            assert len(records) == 3
            assert all(record.retention_until == source.retention_until for record in records)
            for record in records:
                repo.tombstone(record.ref.resource_id)
        for record in records:
            GCSObjectStorage(Settings(), record.ref.owner_id).delete(record)
        assert web.get(endpoint + "/pages/1/image", headers=hdr).status_code == 404
