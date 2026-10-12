"""Exercise authenticated JSONL snapshots through the real web/API/private storage stack."""

import json
import os
import time
from uuid import UUID, uuid4

import httpx
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth.identity import verify_token
from app.db import engine
from app.private_io.repository import PrivateRepository
from app.studio.types import AnnotationContent
from tests.pdf_fixtures import metadata_for
from tests.test_page_rendering import numbered_pdf
from tests.test_upload_integration import headers

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_DATASET_INTEGRATION") != "1",
    reason="Requires local web, admin API, DB, GCS and workers",
)


def test_dataset_snapshots_import_review_splits_privacy_and_access():
    hdr = headers("maintainer@example.test")
    with httpx.Client(base_url="http://web:3000/api/studio", timeout=120) as web:
        data = numbered_pdf()
        metadata = metadata_for(data)
        metadata.pop("assessment_type")
        metadata.pop("page_count")
        metadata.update(
            title="Dataset fixture",
            author="Synthetic author",
            publisher="Local fixture",
            kind="reference",
            source_authority="supplemental",
            license_metadata={"rights": "Synthetic fixture"},
        )
        response = web.post(
            "/upload",
            headers=hdr,
            files={
                "file": ("synthetic.pdf", data, "application/pdf"),
                "metadata": (None, json.dumps(metadata)),
            },
        )
        assert response.status_code == 202, response.text
        doc = response.json()["resource_id"]
        base = "/sources/" + doc
        assert web.post(base + "/render", headers=hdr).status_code == 202
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            pages = web.get(base + "/pages", headers=hdr).json()["pages"]
            if pages:
                break
            time.sleep(0.3)
        assert pages
        payload = {
            "client_annotation_id": str(uuid4()),
            "page_number": 1,
            "bbox": {"x": 10, "y": 20, "width": 100, "height": 50},
            "question": "Synthetic dataset question " + uuid4().hex,
            "response": "Only the positive root",
            "first_error": "Missing negative root",
        }
        response = web.post(base + "/annotations", headers=hdr, json=payload)
        assert response.status_code == 201, response.text
        note = response.json()
        anno = note["id"]
        labels = {k: note[k] for k in AnnotationContent.model_fields}
        edit = {**labels, "expected_revision": 1, "rationale": "Pinned revision two"}
        response = web.patch(base + "/annotations/" + anno, headers=hdr, json=edit)
        assert response.status_code == 200, response.text

        def create():
            response = web.post(
                "/datasets",
                headers=hdr,
                json={
                    "name": "Fixture " + str(uuid4()),
                    "version": "v1",
                    "client_dataset_id": str(uuid4()),
                },
            )
            assert response.status_code == 201, response.text
            return "/datasets/" + response.json()["id"]

        dataset = create()
        case_payload = {
            "document_id": doc,
            "annotation_id": anno,
            "expected_revision": 2,
            "partition": "holdout",
            "label_origin": "assistant_draft",
            "safety": {
                "origin": "synthetic",
                "rights_confirmed": True,
                "text_deidentified": True,
                "crop_reviewed": True,
            },
        }
        response = web.post(dataset + "/cases", headers=hdr, json=case_payload)
        assert response.status_code == 201, response.text
        case = response.json()
        cid = case["case_id"]
        assert case["annotation_revision"] == 2 and case["label_state"] == "draft"
        assert web.post(dataset + "/cases", headers=hdr, json=case_payload).status_code == 201
        assert (
            web.post(
                dataset + "/cases", headers=hdr, json={**case_payload, "partition": "development"}
            ).status_code
            == 409
        )
        assert web.get(dataset + "/export?partition=holdout", headers=hdr).status_code == 409
        preview = web.get(dataset + "/export?partition=holdout&preview=true", headers=hdr)
        assert preview.status_code == 200, preview.text
        pinned = preview.text
        # Review and export follow saved edits while original snapshots remain in history.
        edit = {**labels, "expected_revision": 2, "rationale": "Later editable annotation"}
        assert web.patch(base + "/annotations/" + anno, headers=hdr, json=edit).status_code == 200
        latest = web.get(dataset + "/export?partition=holdout&preview=true", headers=hdr)
        assert json.loads(latest.text)["labels"]["rationale"] == "Later editable annotation"
        assert json.loads(latest.text)["annotation_revision"] == 3
        assert web.get(dataset + f"/cases/{cid}/crop", headers=hdr).content.startswith(b"\x89PNG")
        student = headers()
        for path in (
            "/datasets",
            dataset + "/cases",
            dataset + f"/cases/{cid}/crop",
            dataset + "/export?partition=holdout&preview=true",
        ):
            assert web.get(path, headers=student).status_code == 403
            assert web.get(path).status_code == 401
        assert (
            web.get(
                dataset + "/export?partition=holdout&owner_id=anything", headers=hdr
            ).status_code
            == 422
        )
        # An approved transport record never supplies a local human review.
        imported = create()
        archive = json.loads(pinned)
        archive["label_state"] = "approved"
        body = {"jsonl": json.dumps(archive) + "\n", "safety_reconfirmed": True}
        response = web.post(imported + "/import", headers=hdr, json=body)
        assert response.status_code == 200, response.text
        assert response.json()["imported"] == 1
        assert (
            web.get(imported + "/cases", headers=hdr).json()["cases"][0]["label_state"] == "draft"
        )
        assert web.post(imported + "/import", headers=hdr, json=body).json() == {
            "schema_version": 1,
            "imported": 0,
            "reused": 1,
        }
        tampered = {**archive, "source": {**archive["source"], "sha256": "f" * 64}}
        assert (
            web.post(
                imported + "/import", headers=hdr, json={**body, "jsonl": json.dumps(tampered)}
            ).status_code
            == 404
        )
        bad_crop = {
            **archive,
            "case_id": str(uuid4()),
            "source": {**archive["source"], "crop_sha256": "f" * 64},
        }
        assert (
            web.post(
                imported + "/import", headers=hdr, json={**body, "jsonl": json.dumps(bad_crop)}
            ).status_code
            == 422
        )
        assert len(web.get(imported + "/cases", headers=hdr).json()["cases"]) == 1
        assert (
            web.post(
                dataset + f"/cases/{cid}/review", headers=hdr, json={"labels_reviewed": True}
            ).status_code
            == 204
        )
        approved = web.get(dataset + "/export?partition=holdout", headers=hdr)
        assert (
            approved.status_code == 200 and json.loads(approved.text)["label_state"] == "approved"
        )
        admin_engine = create_engine(
            os.environ["ADMIN_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
        )
        release, chunk, demo = uuid4(), uuid4(), uuid4()
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO global_knowledge.knowledge_releases "
                    "(id,name,version,status,content_hash) VALUES "
                    "(:id,'dataset fixture','v1','published','synthetic')"
                ),
                {"id": release},
            )
            connection.execute(
                text(
                    "INSERT INTO global_knowledge.knowledge_chunks "
                    "(id,publish_release_id,content_text,document_id) VALUES "
                    "(:id,:release,'synthetic heldout',:doc)"
                ),
                {"id": chunk, "release": release, "doc": UUID(doc)},
            )
            connection.execute(
                text(
                    "INSERT INTO global_knowledge.teaching_demonstrations "
                    "(id,created_by_admin_uid,scenario,source_document_id) VALUES "
                    "(:id,'synthetic','synthetic heldout',:doc)"
                ),
                {"id": demo, "doc": UUID(doc)},
            )
            # Even a future publication flag cannot expose a held-out source at runtime.
            connection.execute(
                text("UPDATE global_knowledge.documents SET status='published' WHERE id=:id"),
                {"id": UUID(doc)},
            )
            connection.execute(
                text(
                    "UPDATE global_knowledge.document_pages SET status='published' "
                    "WHERE document_id=:id"
                ),
                {"id": UUID(doc)},
            )
        with admin_engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE global_knowledge.document_regions SET status='published' "
                    "WHERE page_id IN (SELECT id FROM global_knowledge.document_pages "
                    "WHERE document_id=:id)"
                ),
                {"id": UUID(doc)},
            )
        with Session(engine()) as runtime:
            assert (
                runtime.scalar(
                    text("SELECT count(*) FROM published_knowledge.documents WHERE id=:id"),
                    {"id": UUID(doc)},
                )
                == 0
            )
            assert (
                runtime.scalar(
                    text(
                        "SELECT count(*) FROM published_knowledge.document_pages WHERE "
                        "document_id=:id"
                    ),
                    {"id": UUID(doc)},
                )
                == 0
            )
        with Session(engine()) as runtime:
            assert (
                runtime.scalar(
                    text(
                        "SELECT count(*) FROM published_knowledge.document_regions "
                        "WHERE page_id=ANY(:pages)"
                    ),
                    {"pages": [UUID(page["id"]) for page in pages]},
                )
                == 0
            )
        from app.auth.identity import Principal
        from app.datasets.service import owned

        with pytest.raises(LookupError), Session(admin_engine) as session, session.begin():
            owned(
                session,
                Principal(uid="other-maintainer", role="admin"),
                UUID(dataset.split("/")[-1]),
            )
        for key in ("RUNTIME_WORKER_DATABASE_URL", "ADMIN_WORKER_DATABASE_URL"):
            worker_engine = create_engine(
                os.environ[key].replace("postgresql://", "postgresql+psycopg://")
            )
            with pytest.raises(DBAPIError), worker_engine.begin() as connection:
                connection.execute(text("SELECT * FROM global_knowledge.dataset_cases"))
            worker_engine.dispose()
        with Session(engine()) as runtime:
            for table, identity in (("knowledge_chunks", chunk),):
                assert (
                    runtime.scalar(
                        text(f"SELECT count(*) FROM published_knowledge.{table} WHERE id=:id"),
                        {"id": identity},
                    )
                    == 0
                )
        with admin_engine.begin() as connection:
            for table, identity in (
                ("knowledge_chunks", chunk),
                ("teaching_demonstrations", demo),
                ("knowledge_releases", release),
            ):
                connection.execute(
                    text(f"DELETE FROM global_knowledge.{table} WHERE id=:id"), {"id": identity}
                )
        with Session(engine()) as runtime:
            assert (
                runtime.scalar(
                    text("SELECT to_regclass('published_knowledge.teaching_demonstrations')")
                )
                is None
            )
        with pytest.raises(DBAPIError), engine().begin() as connection:
            connection.execute(text("SELECT * FROM global_knowledge.dataset_cases"))
        for url in (engine(), admin_engine):
            with pytest.raises(DBAPIError), url.begin() as connection:
                connection.execute(
                    text(
                        "UPDATE global_knowledge.dataset_cases SET record='{}'::jsonb "
                        "WHERE dataset_id=:id"
                    ),
                    {"id": UUID(dataset.split("/")[-1])},
                )
        principal = verify_token(hdr["Authorization"].split()[1])
        with Session(admin_engine) as session, session.begin():
            PrivateRepository(session, principal).tombstone(UUID(doc))
        assert web.get(dataset + "/cases", headers=hdr).json()["cases"] == []
        assert web.get(dataset + f"/cases/{cid}/crop", headers=hdr).status_code == 404
        assert web.get(dataset + "/export?partition=holdout", headers=hdr).status_code == 409
        admin_engine.dispose()


def test_question_registry_blocks_response_variants_across_distinct_sources():
    from app.datasets.service import lock_split
    from app.studio.service import Conflict
    from tests.test_dataset_jsonl import fixture

    admin_engine = create_engine(
        os.environ["ADMIN_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
    )
    record = fixture()
    record.labels.question = "Unique algebra question " + uuid4().hex
    record.source.sha256 = uuid4().hex + uuid4().hex
    with Session(admin_engine) as session, session.begin():
        lock_split(session, record)
    variant = record.model_copy(deep=True)
    variant.source.sha256 = uuid4().hex + uuid4().hex
    variant.partition = "holdout"
    variant.labels.question = "  " + record.labels.question.upper() + "   "
    variant.labels.response = "A different response"
    with pytest.raises(Conflict), Session(admin_engine) as session, session.begin():
        lock_split(session, variant)
    admin_engine.dispose()


def test_live_label_review_and_reversible_page_annotation_document_deletion():
    hdr = headers("maintainer@example.test")
    data = numbered_pdf()
    metadata = metadata_for(data)
    metadata.pop("assessment_type")
    metadata.pop("page_count")
    metadata.update(
        filename="personal.pdf",
        title="Deletion fixture",
        author="Unspecified",
        publisher="Personal library",
        kind="reference",
        source_authority="supplemental",
        license_metadata={
            "rights": "Private personal-use upload; no publication permission asserted"
        },
    )
    with httpx.Client(base_url="http://web:3000/api/studio", timeout=120) as web:
        response = web.post(
            "/upload",
            headers=hdr,
            files={
                "file": ("personal.pdf", data, "application/pdf"),
                "metadata": (None, json.dumps(metadata)),
            },
        )
        assert response.status_code == 202, response.text
        doc = response.json()["resource_id"]
        base = "/sources/" + doc
        assert web.post(base + "/render", headers=hdr).status_code == 202
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            pages = web.get(base + "/pages", headers=hdr).json()["pages"]
            if pages:
                break
            time.sleep(0.3)
        assert len(pages) == 2
        response = web.post(
            "/datasets",
            headers=hdr,
            json={
                "name": "Delete fixture " + uuid4().hex,
                "version": "v1",
                "client_dataset_id": str(uuid4()),
            },
        )
        assert response.status_code == 201, response.text
        dataset = "/datasets/" + response.json()["id"]
        notes, cases = [], []
        for page in (1, 2):
            response = web.post(
                base + "/annotations",
                headers=hdr,
                json={
                    "client_annotation_id": str(uuid4()),
                    "page_number": page,
                    "bbox": {"x": 10, "y": 20, "width": 100, "height": 50},
                    "question": "Synthetic removal question " + uuid4().hex,
                    "response": "Initial label",
                },
            )
            assert response.status_code == 201, response.text
            note = response.json()
            notes.append(note)
            response = web.post(
                dataset + "/cases",
                headers=hdr,
                json={
                    "document_id": doc,
                    "annotation_id": note["id"],
                    "expected_revision": 1,
                    "partition": "development",
                    "label_origin": "assistant_draft",
                    "safety": {
                        "origin": "synthetic",
                        "rights_confirmed": True,
                        "text_deidentified": True,
                        "crop_reviewed": True,
                    },
                },
            )
            assert response.status_code == 201, response.text
            cases.append(response.json())
        cid = cases[0]["case_id"]
        assert (
            web.post(
                dataset + f"/cases/{cid}/review", headers=hdr, json={"labels_reviewed": True}
            ).status_code
            == 204
        )
        labels = {k: notes[0][k] for k in AnnotationContent.model_fields}
        response = web.patch(
            base + "/annotations/" + notes[0]["id"],
            headers=hdr,
            json={
                **labels,
                "expected_revision": 1,
                "response": "Updated saved response",
                "first_error": "Updated comment",
            },
        )
        assert response.status_code == 200, response.text
        rows = web.get(dataset + "/cases", headers=hdr).json()["cases"]
        updated = next(c for c in rows if c["case_id"] == cid)
        assert updated["labels"]["response"] == "Updated saved response"
        assert updated["labels"]["first_error"] == "Updated comment"
        assert updated["label_state"] == "draft"
        assert web.get(dataset + "/export?partition=development", headers=hdr).status_code == 409
        assert web.get(dataset + f"/cases/{cid}/annotation", headers=hdr).json()["revision"] == 2
        assert (
            web.post(
                dataset + f"/cases/{cid}/review", headers=hdr, json={"labels_reviewed": True}
            ).status_code
            == 204
        )
        approved = web.get(dataset + "/export?partition=development", headers=hdr)
        assert json.loads(approved.text)["labels"]["response"] == "Updated saved response"
        student = headers()
        for path in (base, base + "/pages/2", base + "/annotations/" + notes[1]["id"]):
            assert web.delete(path, headers=student).status_code == 403
            assert web.delete(path).status_code == 401
        assert web.delete(base + "/pages/2", headers=hdr).status_code == 204
        assert [
            p["page_number"] for p in web.get(base + "/pages", headers=hdr).json()["pages"]
        ] == [1]
        assert len(web.get(base + "/annotations", headers=hdr).json()["annotations"]) == 1
        assert len(web.get(dataset + "/cases", headers=hdr).json()["cases"]) == 1
        assert web.get(base + "/pages/2/image", headers=hdr).status_code == 404
        assert (
            web.get(dataset + f"/cases/{cases[1]['case_id']}/crop", headers=hdr).status_code == 404
        )
        assert web.post(base + "/pages/2/restore", headers=hdr).status_code == 204
        assert len(web.get(dataset + "/cases", headers=hdr).json()["cases"]) == 2
        path = base + "/annotations/" + notes[1]["id"]
        assert web.delete(path, headers=hdr).status_code == 204
        assert web.delete(path, headers=hdr).status_code == 204
        assert len(web.get(dataset + "/cases", headers=hdr).json()["cases"]) == 1
        assert web.get(path + "/crop", headers=hdr).status_code == 404
        assert web.post(path + "/restore", headers=hdr).status_code == 204
        assert len(web.get(dataset + "/cases", headers=hdr).json()["cases"]) == 2
        assert web.delete(base, headers=hdr).status_code == 204
        assert web.get(base + "/pages", headers=hdr).status_code == 404
        assert web.get(dataset + "/cases", headers=hdr).json()["cases"] == []
        assert web.get(dataset + "/export?partition=development", headers=hdr).status_code == 409
        assert web.post(base + "/restore", headers=hdr).status_code == 204
        assert len(web.get(dataset + "/cases", headers=hdr).json()["cases"]) == 2
        assert web.get(path + "/crop", headers=hdr).status_code == 200
        # Leave disposable fixture sources removed from the library.
        assert web.delete(base, headers=hdr).status_code == 204
