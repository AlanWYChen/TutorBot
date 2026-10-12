import json
import os
import time
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.auth.identity import verify_token
from app.config import Settings
from app.private_io.repository import PrivateRepository
from app.private_io.storage import GCSObjectStorage
from app.studio.types import AnnotationContent
from tests.pdf_fixtures import metadata_for
from tests.test_page_rendering import numbered_pdf
from tests.test_upload_integration import headers

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_STUDIO_INTEGRATION") != "1",
    reason="Requires local web, admin API, DB, GCS and workers",
)


def test_studio_save_edit_retrieve_private_crop_and_revision_history():
    hdr = headers("maintainer@example.test")
    data = numbered_pdf(rotated=True)
    metadata = metadata_for(data)
    metadata.pop("assessment_type")
    metadata.pop("page_count")
    metadata.update(
        title="Synthetic teacher reference",
        author="Synthetic author",
        publisher="Synthetic publisher",
        kind="reference",
        source_authority="supplemental",
        license_metadata={"rights": "Synthetic fixture only"},
    )
    with httpx.Client(base_url="http://web:3000", timeout=60) as web:
        response = web.post(
            "/api/studio/upload",
            headers=hdr,
            files={
                "file": ("synthetic.pdf", data, "application/pdf"),
                "metadata": (None, json.dumps(metadata)),
            },
        )
        assert response.status_code == 202, response.text
        doc = response.json()["resource_id"]
        base = "/api/studio/sources/" + doc
        assert web.post(base + "/render", headers=hdr).status_code == 202
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            response = web.get(base + "/pages", headers=hdr)
            assert response.status_code == 200, response.text
            pages = response.json()["pages"]
            if pages:
                break
            time.sleep(0.3)
        assert len(pages) == 2 and pages[0]["rotation"] == 90
        student = headers()
        for path in ["/pages", "/pages/1/image", "/annotations"]:
            assert web.get(base + path, headers=student).status_code == 403
            assert web.get(base + path).status_code == 401
        payload = {
            "client_annotation_id": str(uuid4()),
            "page_number": 1,
            "bbox": {"x": 10, "y": 20, "width": 100, "height": 50},
            "question": "Synthetic solve question",
            "response": "Synthetic incomplete working",
            "marks_awarded": 1,
            "marks_possible": 3,
            "first_error": "Missing final root",
            "observed_behaviours": "Only one root is written",
            "observation_status": "observed",
            "intervention": "Ask for both possible roots",
            "rationale": "Verify completeness",
        }
        response = web.post(base + "/annotations", headers=hdr, json=payload)
        assert response.status_code == 201, response.text
        saved = response.json()
        aid = saved["id"]
        assert saved["revision"] == 1 and saved["source_sha256"] == metadata["sha256"]
        assert web.post(base + "/annotations", headers=hdr, json=payload).json()["id"] == aid
        crop = web.get(base + f"/annotations/{aid}/crop", headers=hdr)
        assert crop.status_code == 200 and crop.content.startswith(b"\x89PNG\r\n\x1a\n")
        import pymupdf

        image = pymupdf.Pixmap(crop.content)
        assert (image.width, image.height) == (100, 50)
        assert web.get(base + f"/annotations/{aid}/crop", headers=student).status_code == 403
        edit = {key: saved[key] for key in AnnotationContent.model_fields}
        edit.update(expected_revision=1, question="Corrected synthetic question", marks_awarded=2)
        response = web.patch(base + f"/annotations/{aid}", headers=hdr, json=edit)
        assert response.status_code == 200, response.text
        assert response.json()["revision"] == 2
        assert web.patch(base + f"/annotations/{aid}", headers=hdr, json=edit).status_code == 409
        assert web.get(base + f"/annotations/{aid}/crop", headers=hdr).content == crop.content
        notes = web.get(base + "/annotations", headers=hdr).json()["annotations"]
        assert len(notes) == 1 and notes[0]["question"] == "Corrected synthetic question"
        invalid = {
            **payload,
            "client_annotation_id": str(uuid4()),
            "bbox": {"x": 99999, "y": 0, "width": 10, "height": 10},
        }
        assert web.post(base + "/annotations", headers=hdr, json=invalid).status_code == 422
        assert (
            web.post(
                base + "/annotations", headers=hdr, json={**payload, "student_id": str(uuid4())}
            ).status_code
            == 422
        )
        assert (
            web.post(
                base + "/annotations", headers=hdr, json={**payload, "status": "published"}
            ).status_code
            == 422
        )
        admin_engine = create_engine(
            os.environ["ADMIN_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
        )
        principal = verify_token(hdr["Authorization"].split(" ")[1])
        with Session(admin_engine) as session, session.begin():
            history = session.execute(
                text(
                    "SELECT revision,payload FROM global_knowledge.annotation_revisions "
                    "WHERE annotation_id=:id ORDER BY revision"
                ),
                {"id": UUID(aid)},
            ).all()
            assert [row[0] for row in history] == [1, 2]
            assert history[0][1]["question"] == payload["question"]
            assert (
                session.scalar(
                    text("SELECT status FROM global_knowledge.maintainer_annotations WHERE id=:id"),
                    {"id": UUID(aid)},
                )
                == "draft"
            )
            session.execute(
                text("UPDATE global_knowledge.documents SET status='published' WHERE id=:id"),
                {"id": UUID(doc)},
            )
            session.execute(
                text(
                    "UPDATE global_knowledge.document_pages SET status='published' "
                    "WHERE document_id=:id"
                ),
                {"id": UUID(doc)},
            )
            session.execute(
                text(
                    "UPDATE global_knowledge.document_regions SET status='published' WHERE id=:id"
                ),
                {"id": UUID(saved["region_id"])},
            )
            repo = PrivateRepository(session, principal)
            # Clean up raw fixture bytes while preserving annotation provenance/history.
            records = [repo.tombstone(UUID(doc))]
            for row in session.execute(
                text(
                    "SELECT id FROM global_knowledge.storage_objects "
                    "WHERE owner_id=:owner AND id<>:id AND record->>'sha256' IS NOT NULL "
                    "AND id IN (SELECT crop_manifest_id FROM "
                    "global_knowledge.maintainer_annotations WHERE id=:anno)"
                ),
                {"owner": repo.owner, "id": UUID(doc), "anno": UUID(aid)},
            ).scalars():
                records.append(repo.tombstone(row))
            from uuid import uuid5

            from app.assessments.types import RENDER_VERSION

            for page in pages:
                records.append(
                    repo.tombstone(uuid5(UUID(doc), f"{RENDER_VERSION}/page/{page['page_number']}"))
                )
        from app.db import engine as runtime_engine

        with Session(runtime_engine()) as runtime:
            assert (
                runtime.scalar(
                    text("SELECT count(*) FROM published_knowledge.document_regions WHERE id=:id"),
                    {"id": UUID(saved["region_id"])},
                )
                == 0
            )
            assert (
                runtime.scalar(
                    text("SELECT to_regclass('published_knowledge.maintainer_annotations')")
                )
                is None
            )
        for record in records:
            GCSObjectStorage(Settings(service_mode="admin"), record.ref.owner_id).delete(record)
        assert web.get(base + f"/annotations/{aid}/crop", headers=hdr).status_code == 404
        from sqlalchemy.exc import DBAPIError

        with pytest.raises(DBAPIError), admin_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE global_knowledge.annotation_revisions "
                    "SET payload='{}'::jsonb WHERE annotation_id=:id"
                ),
                {"id": UUID(aid)},
            )
        admin_engine.dispose()
