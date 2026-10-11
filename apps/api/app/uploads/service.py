import json
from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.identity import Principal
from app.config import Settings
from app.db import engine
from app.domain.contracts import (
    AssessmentStatus,
    AssessmentUpload,
    JobAccepted,
    JobState,
    KnowledgeUpload,
    KnowledgeUploadStatus,
)
from app.private_io.repository import PrivateRepository
from app.private_io.storage import GCSObjectStorage
from app.private_io.types import ObjectRef, ObjectStorage
from app.uploads.validation import UploadRejected


def storage_for(owner_id: UUID) -> ObjectStorage:
    return GCSObjectStorage(Settings(), owner_id)


def save_upload(
    principal: Principal,
    metadata: AssessmentUpload | KnowledgeUpload,
    data: bytes,
    key: UUID,
) -> JobAccepted:
    if (principal.role == "student") != isinstance(metadata, AssessmentUpload):
        raise PermissionError("upload_role_mismatch")
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        document_id = uuid5(repo.owner, "upload/" + str(key))
        assessment_id = uuid5(document_id, "assessment") if principal.role == "student" else None
        resource_id = assessment_id or document_id
        # Serialize same-key uploads before any external write. Retries cannot alter
        # metadata, overwrite deleted evidence, or produce more than one job/resource.
        session.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:key,0))"),
            {"key": str(document_id)},
        )
        existing = session.execute(
            text(f"SELECT retention_metadata FROM {repo.schema}.documents WHERE id=:id"),
            {"id": document_id},
        ).scalar_one_or_none()
        if existing is not None:
            if existing.get("upload_metadata") != metadata.model_dump(mode="json"):
                raise UploadRejected("idempotency_conflict", 409)
            try:
                repo.object(document_id)
            except LookupError:
                raise UploadRejected("upload_deleted", 409) from None
            job = repo.enqueue(document_id, "upload/" + str(key))
            return JobAccepted(job_id=job.id, resource_id=resource_id, status=JobState(job.state))
        # A tombstone without a domain document still reserves this resource forever.
        tombstone = session.execute(
            text(f"SELECT deleted_at IS NOT NULL FROM {repo.schema}.storage_objects WHERE id=:id"),
            {"id": document_id},
        ).scalar_one_or_none()
        if tombstone:
            raise UploadRejected("upload_deleted", 409)
        if metadata.curriculum_id is not None:
            published = session.execute(
                text(
                    "SELECT id FROM published_knowledge.curricula WHERE id=:id"
                    if principal.role == "student"
                    else (
                        "SELECT id FROM global_knowledge.curricula "
                        "WHERE id=:id AND status='published'"
                    )
                ),
                {"id": metadata.curriculum_id},
            ).scalar_one_or_none()
            if published is None:
                raise UploadRejected("published_curriculum_required")
        ref = ObjectRef(
            bucket="student-private" if principal.role == "student" else "teaching-private",
            owner_id=repo.owner,
            resource_id=document_id,
            assessment_id=assessment_id,
        )
        record = storage_for(repo.owner).put(ref, data, "application/pdf")
        repo.register(record)
        retention = {
            "retention_until": record.retention_until.isoformat(),
            "generation": record.generation,
            "upload_metadata": metadata.model_dump(mode="json"),
        }
        params: dict[str, object] = {
            "id": document_id,
            "owner": repo.owner,
            "object_key": record.ref.key,
            "sha": record.sha256,
            "size": record.size_bytes,
            "retention": json.dumps(retention),
            "curriculum": metadata.curriculum_id,
        }
        if isinstance(metadata, AssessmentUpload):
            if principal.role != "student":
                raise PermissionError("student_upload_required")
            params["kind"] = metadata.assessment_type.value
            session.execute(
                text(
                    "INSERT INTO student_data.documents "
                    "(id,student_id,kind,object_key,sha256,media_type,size_bytes,source_authority,"
                    "retention_metadata,curriculum_id) VALUES "
                    "(:id,:owner,:kind,:object_key,:sha,'application/pdf',:size,'student',"
                    "CAST(:retention AS jsonb),:curriculum)"
                ),
                params,
            )
            session.execute(
                text(
                    "INSERT INTO student_data.assessments "
                    "(id,student_id,document_id,type,curriculum_id) "
                    "VALUES (:assessment,:owner,:id,:kind,:curriculum)"
                ),
                {**params, "assessment": assessment_id},
            )
        else:
            if principal.role != "admin":
                raise PermissionError("maintainer_upload_required")
            license_metadata = {
                "rights": metadata.license_metadata,
                "title": metadata.title,
                "author": metadata.author,
                "publisher": metadata.publisher,
                "source_url": metadata.source_url,
            }
            session.execute(
                text(
                    "INSERT INTO global_knowledge.documents "
                    "(id,created_by_admin_uid,kind,object_key,sha256,media_type,size_bytes,"
                    "source_authority,license_metadata,retention_metadata,"
                    "curriculum_id,cohort_range) "
                    "VALUES (:id,:uid,:kind,:object_key,:sha,'application/pdf',:size,:authority,"
                    "CAST(:license AS jsonb),CAST(:retention AS jsonb),"
                    ":curriculum,CAST(:cohort AS jsonb))"
                ),
                {
                    **params,
                    "uid": principal.uid,
                    "kind": metadata.kind,
                    "authority": metadata.source_authority,
                    "license": json.dumps(license_metadata),
                    "cohort": json.dumps(
                        metadata.cohort_range.model_dump(mode="json")
                        if metadata.cohort_range
                        else {}
                    ),
                },
            )
        job = repo.enqueue(document_id, "upload/" + str(key))
        return JobAccepted(job_id=job.id, resource_id=resource_id, status=JobState(job.state))


def locate(repo: PrivateRepository, resource_id: UUID, principal: Principal) -> UUID:
    if principal.role == "student":
        document = repo.session.execute(
            text(
                "SELECT document_id FROM student_data.assessments "
                "WHERE id=:id AND student_id=:owner"
            ),
            {"id": resource_id, "owner": repo.owner},
        ).scalar_one_or_none()
    else:
        document = repo.session.execute(
            text(
                "SELECT id FROM global_knowledge.documents "
                "WHERE id=:id AND created_by_admin_uid=:uid"
            ),
            {"id": resource_id, "uid": principal.uid},
        ).scalar_one_or_none()
    if document is None:
        raise LookupError("document_not_found")
    return UUID(str(document))


def read_upload(principal: Principal, resource_id: UUID) -> bytes:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        record = repo.object(locate(repo, resource_id, principal))
        return storage_for(repo.owner).get(record)


def upload_status(
    principal: Principal, resource_id: UUID
) -> AssessmentStatus | KnowledgeUploadStatus:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        document = locate(repo, resource_id, principal)
        repo.object(document)
        row: dict[str, Any] = session.execute(
            text(f"SELECT retention_metadata FROM {repo.schema}.documents WHERE id=:id"),
            {"id": document},
        ).scalar_one()
        job: UUID = session.execute(
            text(
                f"SELECT id FROM {repo.schema}.jobs "
                f"WHERE object_id=:id AND {repo.owner_column}=:owner "
                "ORDER BY created_at LIMIT 1"
            ),
            {"id": document, "owner": repo.owner},
        ).scalar_one()
        status = repo.status(job)
        if principal.role == "admin":
            return KnowledgeUploadStatus(
                document_id=resource_id,
                job_id=job,
                status=JobState(status.state),
                page_count=row["upload_metadata"]["page_count"],
            )
        # Success verifies stored bytes only, never mathematical extraction or marking.
        return AssessmentStatus(
            assessment_id=resource_id,
            job_id=job,
            status=JobState(status.state),
            verified_state="unverified",
            page_count=row["upload_metadata"]["page_count"],
            error_code="processing_failed" if status.state == "failed" else None,
        )
