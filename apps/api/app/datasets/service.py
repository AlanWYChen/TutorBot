import hashlib
import time
from uuid import UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assessments.types import RENDER_VERSION
from app.auth.identity import Principal
from app.datasets.jsonl import parse_jsonl, privacy_check, question_hash, serialize
from app.datasets.types import (
    CaseAdd,
    CaseRecord,
    DatasetCreate,
    DatasetView,
    ImportResult,
    SourceLocator,
)
from app.db import engine
from app.private_io.repository import PrivateRepository
from app.studio import service as studio
from app.studio.types import AnnotationContent, AnnotationCreate, AnnotationView


def owned(session: Session, principal: Principal, dataset: UUID) -> None:
    if principal.role != "admin" or not session.scalar(
        text(
            "SELECT id FROM global_knowledge.annotation_datasets WHERE id=:id AND "
            "created_by_admin_uid=:uid"
        ),
        {"id": dataset, "uid": principal.uid},
    ):
        raise LookupError("dataset not found")


def create(principal: Principal, payload: DatasetCreate) -> DatasetView:
    if principal.role != "admin":
        raise PermissionError("maintainer required")
    dataset = uuid5(
        uuid5(UUID("09ae7be3-44d0-40bf-bb30-b740e72a1d2b"), principal.uid),
        str(payload.client_dataset_id),
    )
    with Session(engine()) as session, session.begin():
        session.execute(
            text(
                "INSERT INTO global_knowledge.annotation_datasets "
                "(id,created_by_admin_uid,name,version) VALUES (:id,:uid,:name,:version) "
                "ON CONFLICT DO NOTHING"
            ),
            {"id": dataset, "uid": principal.uid, "name": payload.name, "version": payload.version},
        )
        row = session.execute(
            text(
                "SELECT name,version FROM global_knowledge.annotation_datasets "
                "WHERE id=:id AND created_by_admin_uid=:uid"
            ),
            {"id": dataset, "uid": principal.uid},
        ).one_or_none()
        if row is None or row != (payload.name, payload.version):
            raise studio.Conflict("dataset identity conflicts")
        return view(session, principal, dataset)


def view(session: Session, principal: Principal, dataset: UUID) -> DatasetView:
    owned(session, principal, dataset)
    row = session.execute(
        text("SELECT name,version FROM global_knowledge.annotation_datasets WHERE id=:id"),
        {"id": dataset},
    ).one()
    records = cases_in_session(session, principal, dataset)
    return DatasetView(
        id=dataset,
        name=row[0],
        version=row[1],
        development=sum(r.partition == "development" for r in records),
        holdout=sum(r.partition == "holdout" for r in records),
        approved=sum(r.label_state == "approved" for r in records),
    )


def recent(principal: Principal) -> list[DatasetView]:
    with Session(engine()) as session, session.begin():
        ids: list[UUID] = list(
            session.execute(
                text(
                    "SELECT id FROM global_knowledge.annotation_datasets "
                    "WHERE created_by_admin_uid=:uid ORDER BY created_at DESC LIMIT 20"
                ),
                {"uid": principal.uid},
            ).scalars()
        )
        return [view(session, principal, dataset) for dataset in ids]


def lock_split(session: Session, record: CaseRecord) -> str:
    hashed = question_hash(record.labels.question)
    for table, column, value in (
        ("dataset_source_partitions", "source_sha256", record.source.sha256),
        ("dataset_question_partitions", "question_hash", hashed),
    ):
        session.execute(
            text(
                f"INSERT INTO global_knowledge.{table} ({column},partition) "
                "VALUES (:key,:partition) ON CONFLICT DO NOTHING"
            ),
            {"key": value, "partition": record.partition},
        )
        partition = session.scalar(
            text(f"SELECT partition FROM global_knowledge.{table} WHERE {column}=:key"),
            {"key": value},
        )
        if partition != record.partition:
            raise studio.Conflict("source or question is reserved for the other partition")
    if record.partition == "holdout" and session.scalar(
        text(
            "SELECT id FROM global_knowledge.documents WHERE sha256=:sha AND "
            "status='published' LIMIT 1"
        ),
        {"sha": record.source.sha256},
    ):
        raise studio.Conflict("published source cannot become holdout")
    return hashed


def add_record(
    session: Session,
    principal: Principal,
    dataset: UUID,
    document: UUID,
    annotation: UUID,
    record: CaseRecord,
    local_revision: int | None = None,
) -> bool:
    owned(session, principal, dataset)
    session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:id,0))"),
        {"id": "dataset/" + str(dataset)},
    )
    privacy_check(record)
    hashed = lock_split(session, record)
    existing = session.scalar(
        text(
            "SELECT record FROM global_knowledge.dataset_cases WHERE dataset_id=:dataset AND id=:id"
        ),
        {"dataset": dataset, "id": record.case_id},
    )
    if existing is not None:
        old = CaseRecord.model_validate(existing)
        if old != record.model_copy(update={"label_state": "draft"}):
            raise studio.Conflict("case identity conflicts")
        return False
    if (
        session.scalar(
            text("SELECT count(*) FROM global_knowledge.dataset_cases WHERE dataset_id=:id"),
            {"id": dataset},
        )
        >= 50
    ):
        raise ValueError("dataset supports at most 50 cases")
    session.execute(
        text(
            "INSERT INTO global_knowledge.dataset_cases "
            "(dataset_id,id,document_id,annotation_id,annotation_revision,record,source_sha256,"
            "question_hash,partition) VALUES "
            "(:dataset,:id,:doc,:anno,:revision,CAST(:record AS jsonb),"
            ":sha,:question,:partition)"
        ),
        {
            "dataset": dataset,
            "id": record.case_id,
            "doc": document,
            "anno": annotation,
            "revision": local_revision or record.annotation_revision,
            "record": record.model_copy(update={"label_state": "draft"}).model_dump_json(),
            "sha": record.source.sha256,
            "question": hashed,
            "partition": record.partition,
        },
    )
    return True


def add(principal: Principal, dataset: UUID, payload: CaseAdd) -> CaseRecord:
    with Session(engine()) as session, session.begin():
        owned(session, principal, dataset)
        session.execute(text("SELECT pg_advisory_xact_lock(730013)"))
        repo = PrivateRepository(session, principal)
        note = studio.get_in_session(repo, principal, payload.document_id, payload.annotation_id)
        if note.revision != payload.expected_revision:
            raise studio.Conflict("annotation changed; review current revision")
        crop_id = session.scalar(
            text(
                "SELECT crop_manifest_id FROM global_knowledge.maintainer_annotations WHERE id=:id"
            ),
            {"id": note.id},
        )
        record = CaseRecord(
            case_id=uuid5(note.id, f"revision/{note.revision}"),
            partition=payload.partition,
            label_origin=payload.label_origin,
            source=SourceLocator(
                sha256=note.source_sha256,
                page_number=note.page_number,
                bbox=note.bbox,
                render_version=note.render_version,
                crop_sha256=repo.object(crop_id).sha256,
            ),
            annotation_revision=note.revision,
            labels=AnnotationContent.model_validate(studio.content(note)),
            safety=payload.safety,
        )
        add_record(session, principal, dataset, payload.document_id, note.id, record)
        return record


def validate_edit(session: Session, annotation: UUID, labels: AnnotationContent) -> None:
    rows: list[dict[str, object]] = list(
        session.execute(
            text("SELECT record FROM global_knowledge.dataset_cases WHERE annotation_id=:id"),
            {"id": annotation},
        ).scalars()
    )
    for raw in rows:
        record = CaseRecord.model_validate(raw).model_copy(update={"labels": labels})
        privacy_check(record)
        lock_split(session, record)


def cases_in_session(session: Session, principal: Principal, dataset: UUID) -> list[CaseRecord]:
    owned(session, principal, dataset)
    rows = session.execute(
        text(
            "SELECT c.record,c.annotation_revision as "
            "pinned_revision,a.revision,a.payload,r.id as reviewed "
            "FROM global_knowledge.dataset_cases c "
            "JOIN global_knowledge.maintainer_annotations a ON a.id=c.annotation_id "
            "JOIN global_knowledge.document_regions g ON g.id=a.region_id "
            "JOIN global_knowledge.document_pages p ON p.id=g.page_id "
            "JOIN global_knowledge.storage_objects o ON o.id=c.document_id "
            "LEFT JOIN global_knowledge.dataset_case_reviews r ON r.dataset_id=c.dataset_id "
            "AND r.case_id=c.id AND r.annotation_revision=a.revision "
            "WHERE c.dataset_id=:id AND a.created_by_admin_uid=:uid AND o.deleted_at IS NULL "
            "AND a.deleted_at IS NULL AND p.deleted_at IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM global_knowledge.dataset_cases newer "
            "WHERE newer.dataset_id=c.dataset_id AND newer.annotation_id=c.annotation_id "
            "AND newer.annotation_revision>c.annotation_revision) "
            "ORDER BY c.partition,c.source_sha256,(c.record->'source'->>'page_number')::int,c.id"
        ),
        {"id": dataset, "uid": principal.uid},
    ).mappings()
    result = []
    for row in rows:
        record = CaseRecord.model_validate(row["record"])
        changed = row["revision"] != row["pinned_revision"]
        result.append(
            record.model_copy(
                update={
                    "labels": AnnotationContent.model_validate(row["payload"]),
                    "annotation_revision": row["revision"]
                    if changed
                    else record.annotation_revision,
                    "label_origin": "maintainer" if changed else record.label_origin,
                    "label_state": "approved" if row["reviewed"] else "draft",
                }
            )
        )
    return result


def annotation(principal: Principal, dataset: UUID, case: UUID) -> AnnotationView:
    with Session(engine()) as session, session.begin():
        owned(session, principal, dataset)
        row = session.execute(
            text(
                "SELECT document_id,annotation_id FROM global_knowledge.dataset_cases "
                "WHERE dataset_id=:dataset AND id=:case"
            ),
            {"dataset": dataset, "case": case},
        ).one_or_none()
        if row is None:
            raise LookupError("case not found")
        return studio.get_in_session(
            PrivateRepository(session, principal), principal, row[0], row[1]
        )


def crop(principal: Principal, dataset: UUID, case: UUID) -> bytes:
    with Session(engine()) as session, session.begin():
        owned(session, principal, dataset)
        row = session.execute(
            text(
                "SELECT document_id,annotation_id FROM "
                "global_knowledge.dataset_cases WHERE dataset_id=:dataset AND id=:case"
            ),
            {"dataset": dataset, "case": case},
        ).one_or_none()
        if row is None:
            raise LookupError("case not found")
    return studio.crop(principal, row[0], row[1])


def cases(principal: Principal, dataset: UUID) -> list[CaseRecord]:
    with Session(engine()) as session, session.begin():
        return cases_in_session(session, principal, dataset)


def approve(principal: Principal, dataset: UUID, case: UUID) -> None:
    with Session(engine()) as session, session.begin():
        session.execute(text("SELECT pg_advisory_xact_lock(730013)"))
        records = cases_in_session(session, principal, dataset)
        record = next((item for item in records if item.case_id == case), None)
        if record is None:
            raise LookupError("case not found")
        privacy_check(record)
        session.execute(
            text(
                "INSERT INTO global_knowledge.dataset_case_reviews "
                "(id,dataset_id,case_id,reviewed_by_admin_uid,annotation_revision) "
                "VALUES (:id,:dataset,:case,:uid,:revision) "
                "ON CONFLICT DO NOTHING"
            ),
            {
                "id": uuid4(),
                "dataset": dataset,
                "case": case,
                "uid": principal.uid,
                "revision": session.scalar(
                    text(
                        "SELECT a.revision FROM global_knowledge.dataset_cases c "
                        "JOIN global_knowledge.maintainer_annotations a ON a.id=c.annotation_id "
                        "WHERE c.dataset_id=:dataset AND c.id=:case"
                    ),
                    {"dataset": dataset, "case": case},
                ),
            },
        )


def export(principal: Principal, dataset: UUID, partition: str, preview: bool = False) -> str:
    records = [record for record in cases(principal, dataset) if record.partition == partition]
    if not preview:
        records = [record for record in records if record.label_state == "approved"]
    if not records:
        raise studio.Conflict("no eligible cases; review labels before evaluation export")
    return serialize(records)


def import_archive(principal: Principal, dataset: UUID, jsonl: str) -> ImportResult:
    records = parse_jsonl(jsonl)
    imported = reused = 0
    deadline = time.monotonic() + 60
    with Session(engine()) as session, session.begin():
        owned(session, principal, dataset)
        session.execute(text("SELECT pg_advisory_xact_lock(730013)"))
        repo = PrivateRepository(session, principal)
        targets: dict[UUID, UUID] = {}
        # Validate the complete archive, owner/source availability and split consistency first.
        for record in sorted(
            records, key=lambda r: (r.source.sha256, question_hash(r.labels.question))
        ):
            doc = session.scalar(
                text(
                    "SELECT d.id FROM global_knowledge.documents d "
                    "JOIN global_knowledge.storage_objects o ON o.id=d.id AND o.owner_id=:owner "
                    "WHERE d.sha256=:sha AND d.created_by_admin_uid=:uid AND o.deleted_at IS NULL "
                    "ORDER BY d.created_at LIMIT 1"
                ),
                {"sha": record.source.sha256, "owner": repo.owner, "uid": principal.uid},
            )
            if doc is None or repo.object(doc).sha256 != record.source.sha256:
                raise LookupError("owned source PDF required")
            if record.source.render_version != RENDER_VERSION:
                raise ValueError("renderer version mismatch")
            page = studio.page_row(repo, doc, record.source.page_number)
            b = record.source.bbox
            if (
                b.x + b.width > page["dimensions"]["width"]
                or b.y + b.height > page["dimensions"]["height"]
            ):
                raise ValueError("source box exceeds page")
            targets[record.case_id] = doc
            lock_split(session, record)
        for record in records:
            if time.monotonic() > deadline:
                raise ValueError("import processing limit exceeded")
            doc = targets[record.case_id]
            original = session.execute(
                text(
                    "SELECT annotation_id,annotation_revision FROM "
                    "global_knowledge.dataset_cases WHERE dataset_id=:dataset AND id=:id"
                ),
                {"dataset": dataset, "id": record.case_id},
            ).one_or_none()
            if original:
                if add_record(
                    session,
                    principal,
                    dataset,
                    doc,
                    original[0],
                    record.model_copy(update={"label_state": "draft"}),
                ):
                    imported += 1
                else:
                    reused += 1
                continue
            note = studio.create_in_session(
                session,
                principal,
                doc,
                AnnotationCreate(
                    **record.labels.model_dump(),
                    client_annotation_id=uuid5(
                        record.case_id,
                        hashlib.sha256(record.labels.model_dump_json().encode()).hexdigest(),
                    ),
                    page_number=record.source.page_number,
                    bbox=record.source.bbox,
                ),
            )
            crop_id = session.scalar(
                text(
                    "SELECT crop_manifest_id FROM global_knowledge.maintainer_annotations "
                    "WHERE id=:id"
                ),
                {"id": note.id},
            )
            if repo.object(crop_id).sha256 != record.source.crop_sha256:
                raise ValueError("crop integrity mismatch")
            normalized = record.model_copy(update={"label_state": "draft"})
            imported += int(
                add_record(session, principal, dataset, doc, note.id, normalized, note.revision)
            )
    return ImportResult(imported=imported, reused=reused)
