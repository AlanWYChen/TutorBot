import json
import subprocess
import sys
from typing import Any
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assessments.types import (
    RENDER_VERSION,
    AssessmentListItem,
    CandidateView,
    PageView,
)
from app.auth.identity import Principal
from app.config import Settings
from app.db import engine
from app.domain.contracts import BoundingBox, JobAccepted, JobState
from app.private_io.repository import PrivateRepository
from app.private_io.types import ObjectRef, StorageError
from app.studio.types import AnnotationContent, AnnotationCreate, AnnotationEdit, AnnotationView
from app.uploads.service import locate, storage_for


class Conflict(Exception):
    pass


def source(repo: PrivateRepository, principal: Principal, document: UUID) -> None:
    locate(repo, document, principal)
    repo.object(document)


def recent(principal: Principal) -> list[AssessmentListItem]:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        rows = session.execute(
            text(
                "SELECT d.id,d.retention_metadata,j.state, "
                "(SELECT count(*) FROM global_knowledge.document_pages p WHERE p.document_id=d.id "
                "AND p.deleted_at IS NULL) AS visible_pages, "
                "EXISTS(SELECT 1 FROM global_knowledge.document_pages p WHERE p.document_id=d.id) "
                "AS rendered FROM global_knowledge.documents d "
                "JOIN global_knowledge.storage_objects o ON o.id=d.id AND o.owner_id=:owner "
                "LEFT JOIN global_knowledge.jobs j ON j.object_id=d.id AND j.owner_id=:owner "
                "AND j.kind='render_document' WHERE d.created_by_admin_uid=:uid "
                "AND o.deleted_at IS NULL ORDER BY d.created_at DESC,d.id DESC LIMIT 20"
            ),
            {"owner": repo.owner, "uid": principal.uid},
        ).mappings()
        return [
            AssessmentListItem(
                id=row["id"],
                filename=row["retention_metadata"]["upload_metadata"]["filename"],
                page_count=row["visible_pages"]
                if row["rendered"]
                else row["retention_metadata"]["upload_metadata"]["page_count"],
                state=row["state"] or "not_prepared",
            )
            for row in rows
            if "upload_metadata" in row["retention_metadata"]
        ]


def prepare(principal: Principal, document: UUID) -> JobAccepted:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        source(repo, principal, document)
        job = repo.enqueue_render(document)
        return JobAccepted(job_id=job.id, resource_id=document, status=JobState(job.state))


def page_row(repo: PrivateRepository, document: UUID, number: int) -> dict[str, Any]:
    row = (
        repo.session.execute(
            text(
                "SELECT * FROM global_knowledge.document_pages "
                "WHERE document_id=:id AND page_num=:page "
                "AND deleted_at IS NULL AND dimensions->>'render_version'=:version"
            ),
            {"id": document, "page": number, "version": RENDER_VERSION},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        raise LookupError("page not found")
    return dict(row)


def pages(principal: Principal, document: UUID) -> list[PageView]:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        source(repo, principal, document)
        rows = session.execute(
            text(
                "SELECT * FROM global_knowledge.document_pages WHERE document_id=:id "
                "AND deleted_at IS NULL AND "
                "dimensions->>'render_version'=:version ORDER BY page_num"
            ),
            {"id": document, "version": RENDER_VERSION},
        ).mappings()
        result = []
        for row in rows:
            regions = session.execute(
                text(
                    "SELECT id,bbox,kind FROM global_knowledge.document_regions WHERE page_id=:id "
                    "AND kind LIKE 'question_candidate:%'"
                ),
                {"id": row["id"]},
            ).mappings()
            candidates = [
                CandidateView(
                    id=r["id"],
                    bbox=BoundingBox.model_validate(r["bbox"]),
                    label="Possible question " + r["kind"].split(":")[1],
                )
                for r in regions
            ]
            candidates.sort(key=lambda c: int(c.label.rsplit(" ", 1)[1]))
            d = row["dimensions"]
            result.append(
                PageView(
                    id=row["id"],
                    page_number=row["page_num"],
                    width=d["width"],
                    height=d["height"],
                    rotation=d["rotation"],
                    render_version=RENDER_VERSION,
                    candidates=candidates,
                )
            )
        return result


def image_record(repo: PrivateRepository, document: UUID, number: int) -> UUID:
    row = page_row(repo, document, number)
    image = uuid5(document, f"{RENDER_VERSION}/page/{number}")
    if repo.object(image).ref.key != row["image_object_key"]:
        raise LookupError("page not found")
    return image


def image(principal: Principal, document: UUID, number: int) -> bytes:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        source(repo, principal, document)
        return storage_for(repo.owner).get(repo.object(image_record(repo, document, number)))


def content(payload: AnnotationContent) -> dict[str, Any]:
    return AnnotationContent.model_validate(
        payload.model_dump(include=set(AnnotationContent.model_fields))
    ).model_dump(mode="json")


def create(principal: Principal, document: UUID, payload: AnnotationCreate) -> AnnotationView:
    with Session(engine()) as session, session.begin():
        return create_in_session(session, principal, document, payload)


def create_in_session(
    session: Session, principal: Principal, document: UUID, payload: AnnotationCreate
) -> AnnotationView:
    repo = PrivateRepository(session, principal)
    source(repo, principal, document)
    annotation_id = uuid5(document, str(payload.client_annotation_id))
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:id,0))"),
        {"id": str(annotation_id)},
    )
    existing = session.scalar(
        text("SELECT id FROM global_knowledge.maintainer_annotations WHERE id=:id"),
        {"id": annotation_id},
    )
    if existing:
        previous = get_in_session(repo, principal, document, annotation_id)
        if (
            content(previous) != content(payload)
            or previous.bbox != payload.bbox
            or previous.page_number != payload.page_number
        ):
            raise Conflict("annotation retry conflicts")
        return previous
    page = page_row(repo, document, payload.page_number)
    box = payload.bbox
    if (
        box.x + box.width > page["dimensions"]["width"]
        or box.y + box.height > page["dimensions"]["height"]
    ):
        raise ValueError("source box exceeds page")
    source_record = repo.object(document)
    page_record = repo.object(image_record(repo, document, payload.page_number))
    png = storage_for(repo.owner).get(page_record)
    try:
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "app.studio.crop_image",
                str(box.x),
                str(box.y),
                str(box.width),
                str(box.height),
            ],
            input=png,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=10,
            check=True,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
        )
        if (
            not result.stdout.startswith(b"\x89PNG\r\n\x1a\n")
            or len(result.stdout) > 25 * 1024 * 1024
        ):
            raise ValueError
    except Exception:
        raise StorageError("crop unavailable") from None
    crop_id = uuid5(annotation_id, "crop-v1")
    # Concrete adapter supports inherited retention; namespace always resolves from auth.
    from app.private_io.storage import GCSObjectStorage

    crop = GCSObjectStorage(Settings(), repo.owner).put(
        ObjectRef(bucket="teaching-private", owner_id=repo.owner, resource_id=crop_id),
        result.stdout,
        "image/png",
        retention_until=source_record.retention_until,
    )
    repo.register(crop)
    region_id = uuid5(annotation_id, "source-region")
    session.execute(
        text(
            "INSERT INTO global_knowledge.document_regions "
            "(id,page_id,bbox,kind,crop_key,extraction_confidence) "
            "VALUES (:id,:page,CAST(:box AS jsonb),'maintainer_annotation',:key,1)"
        ),
        {
            "id": region_id,
            "page": page["id"],
            "box": box.model_dump_json(),
            "key": crop.ref.key,
        },
    )
    data = content(payload)
    session.execute(
        text(
            "INSERT INTO global_knowledge.maintainer_annotations "
            "(id,region_id,created_by_admin_uid,annotation,rationale,payload,crop_manifest_id,"
            "source_sha256) VALUES (:id,:region,:uid,:question,:rationale,"
            "CAST(:payload AS jsonb),"
            ":crop,:sha)"
        ),
        {
            "id": annotation_id,
            "region": region_id,
            "uid": principal.uid,
            "question": payload.question,
            "rationale": payload.rationale,
            "payload": json.dumps(data),
            "crop": crop_id,
            "sha": source_record.sha256,
        },
    )
    revision(session, principal, annotation_id, 1, data)
    return get_in_session(repo, principal, document, annotation_id)


def revision(
    session: Session, principal: Principal, annotation: UUID, number: int, payload: dict[str, Any]
) -> None:
    session.execute(
        text(
            "INSERT INTO global_knowledge.annotation_revisions "
            "(id,annotation_id,revision,payload,created_by_admin_uid) "
            "VALUES (:id,:annotation,:revision,CAST(:payload AS jsonb),:uid)"
        ),
        {
            "id": uuid4(),
            "annotation": annotation,
            "revision": number,
            "payload": json.dumps(payload),
            "uid": principal.uid,
        },
    )


def get_in_session(
    repo: PrivateRepository, principal: Principal, document: UUID, annotation: UUID
) -> AnnotationView:
    source(repo, principal, document)
    row = (
        repo.session.execute(
            text(
                "SELECT a.*,r.bbox,p.page_num,p.dimensions "
                "FROM global_knowledge.maintainer_annotations a "
                "JOIN global_knowledge.document_regions r ON r.id=a.region_id "
                "JOIN global_knowledge.document_pages p ON p.id=r.page_id "
                "WHERE a.id=:id AND a.created_by_admin_uid=:uid AND p.document_id=:document "
                "AND a.deleted_at IS NULL AND p.deleted_at IS NULL"
            ),
            {"id": annotation, "uid": principal.uid, "document": document},
        )
        .mappings()
        .one_or_none()
    )
    if row is None or not row["payload"]:
        raise LookupError("annotation not found")
    return AnnotationView(
        **row["payload"],
        id=row["id"],
        document_id=document,
        region_id=row["region_id"],
        bbox=row["bbox"],
        page_number=row["page_num"],
        revision=row["revision"],
        source_sha256=row["source_sha256"],
        render_version=row["dimensions"]["render_version"],
    )


def annotations(principal: Principal, document: UUID) -> list[AnnotationView]:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        source(repo, principal, document)
        ids: list[UUID] = list(
            session.execute(
                text(
                    "SELECT a.id FROM global_knowledge.maintainer_annotations a "
                    "JOIN global_knowledge.document_regions r ON r.id=a.region_id "
                    "JOIN global_knowledge.document_pages p ON p.id=r.page_id "
                    "WHERE p.document_id=:id AND a.created_by_admin_uid=:uid "
                    "AND a.deleted_at IS NULL AND p.deleted_at IS NULL AND a.payload<>'{}'::jsonb "
                    "ORDER BY p.page_num,a.created_at,a.id LIMIT 200"
                ),
                {"id": document, "uid": principal.uid},
            )
            .scalars()
            .all()
        )
        return [get_in_session(repo, principal, document, annotation) for annotation in ids]


def edit(
    principal: Principal, document: UUID, annotation: UUID, payload: AnnotationEdit
) -> AnnotationView:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        session.execute(text("SELECT pg_advisory_xact_lock(730013)"))
        get_in_session(repo, principal, document, annotation)
        data = content(payload)
        from app.datasets.service import validate_edit

        validate_edit(session, annotation, payload)

        number = session.scalar(
            text(
                "UPDATE global_knowledge.maintainer_annotations "
                "SET payload=CAST(:data AS jsonb),annotation=:question,rationale=:rationale,"
                "revision=revision+1 WHERE id=:id AND created_by_admin_uid=:uid "
                "AND revision=:expected RETURNING revision"
            ),
            {
                "data": json.dumps(data),
                "question": payload.question,
                "rationale": payload.rationale,
                "id": annotation,
                "uid": principal.uid,
                "expected": payload.expected_revision,
            },
        )
        if number is None:
            raise Conflict("annotation changed; reload before editing")
        revision(session, principal, annotation, number, data)
        return get_in_session(repo, principal, document, annotation)


def crop(principal: Principal, document: UUID, annotation: UUID) -> bytes:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        get_in_session(repo, principal, document, annotation)
        crop_id = session.scalar(
            text(
                "SELECT crop_manifest_id FROM global_knowledge.maintainer_annotations WHERE id=:id"
            ),
            {"id": annotation},
        )
        return storage_for(repo.owner).get(repo.object(crop_id))


def remove(
    principal: Principal,
    document: UUID,
    *,
    page: int | None = None,
    annotation: UUID | None = None,
    restore: bool = False,
) -> None:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        locate(repo, document, principal)
        session.execute(text("SELECT pg_advisory_xact_lock(730013)"))
        if page is None and annotation is None:
            if not restore:
                repo.tombstone(document)
                return
            from app.private_io.types import StoredObject

            raw = session.scalar(
                text(
                    "SELECT record FROM global_knowledge.storage_objects "
                    "WHERE id=:id AND owner_id=:owner"
                ),
                {"id": document, "owner": repo.owner},
            )
            if raw is None:
                raise LookupError("source not found")
            storage_for(repo.owner).get(StoredObject.model_validate(raw))
            session.execute(
                text(
                    "UPDATE global_knowledge.storage_objects SET deleted_at=NULL "
                    "WHERE id=:id AND owner_id=:owner"
                ),
                {"id": document, "owner": repo.owner},
            )
            session.execute(
                text(
                    "UPDATE global_knowledge.jobs SET state='queued',attempts=0,"
                    "available_at=now(),dispatched_at=NULL,lease_token=NULL,lease_until=NULL "
                    "WHERE object_id=:id AND owner_id=:owner AND state='cancelled'"
                ),
                {"id": document, "owner": repo.owner},
            )
            return
        source(repo, principal, document)
        if annotation is not None:
            row = session.scalar(
                text(
                    "SELECT a.id FROM global_knowledge.maintainer_annotations a "
                    "JOIN global_knowledge.document_regions r ON r.id=a.region_id "
                    "JOIN global_knowledge.document_pages p ON p.id=r.page_id "
                    "WHERE a.id=:annotation AND a.created_by_admin_uid=:uid AND p.document_id=:doc "
                    "AND p.deleted_at IS NULL"
                ),
                {"annotation": annotation, "uid": principal.uid, "doc": document},
            )
            table = "maintainer_annotations"
        else:
            row = session.scalar(
                text(
                    "SELECT id FROM global_knowledge.document_pages "
                    "WHERE document_id=:doc AND page_num=:page"
                ),
                {"doc": document, "page": page},
            )
            table = "document_pages"
        if row is None:
            raise LookupError("item not found")
        value = "NULL" if restore else "COALESCE(deleted_at,now())"
        session.execute(
            text(f"UPDATE global_knowledge.{table} SET deleted_at={value} WHERE id=:id"),
            {"id": row},
        )
