from typing import Any
from uuid import UUID, uuid5

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.assessments.types import (
    RENDER_VERSION,
    AssessmentList,
    AssessmentListItem,
    AssessmentPages,
    CandidateView,
    PageView,
)
from app.auth.identity import Principal
from app.db import engine
from app.domain.contracts import BoundingBox, JobAccepted, JobState
from app.private_io.repository import PrivateRepository
from app.uploads.service import locate, storage_for


def prepare(principal: Principal, assessment_id: UUID) -> JobAccepted:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        document = locate(repo, assessment_id, principal)
        job = repo.enqueue_render(document)
        return JobAccepted(job_id=job.id, resource_id=assessment_id, status=JobState(job.state))


def recent(principal: Principal) -> AssessmentList:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        rows = session.execute(
            text(
                "SELECT a.id,d.retention_metadata,j.state FROM student_data.assessments a "
                "JOIN student_data.documents d ON d.id=a.document_id AND d.student_id=a.student_id "
                "JOIN student_data.storage_objects o ON o.id=d.id AND o.student_id=d.student_id "
                "LEFT JOIN student_data.jobs j ON j.object_id=d.id AND j.student_id=d.student_id "
                "AND j.kind='render_document' WHERE a.student_id=:owner AND o.deleted_at IS NULL "
                "ORDER BY a.created_at DESC,a.id DESC LIMIT 20"
            ),
            {"owner": repo.owner},
        ).mappings()
        return AssessmentList(
            assessments=[
                AssessmentListItem(
                    id=row["id"],
                    filename=row["retention_metadata"]["upload_metadata"]["filename"],
                    page_count=row["retention_metadata"]["upload_metadata"]["page_count"],
                    state=row["state"] or "not_prepared",
                )
                for row in rows
                if "upload_metadata" in row["retention_metadata"]
            ]
        )


def page_rows(repo: PrivateRepository, document: UUID) -> list[dict[str, Any]]:
    return [
        dict(row)
        for row in repo.session.execute(
            text(
                "SELECT * FROM student_data.document_pages WHERE document_id=:document "
                "AND student_id=:owner AND dimensions->>'render_version'=:version ORDER BY page_num"
            ),
            {"document": document, "owner": repo.owner, "version": RENDER_VERSION},
        ).mappings()
    ]


def pages(principal: Principal, assessment_id: UUID) -> AssessmentPages:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        document = locate(repo, assessment_id, principal)
        repo.object(document)  # Parent deletion hides every derivative too.
        result = []
        for row in page_rows(repo, document):
            candidates = []
            regions = session.execute(
                text(
                    "SELECT id,bbox,kind FROM student_data.document_regions WHERE page_id=:page "
                    "AND student_id=:owner AND kind LIKE 'question_candidate:%' "
                    "ORDER BY created_at,id"
                ),
                {"page": row["id"], "owner": repo.owner},
            ).mappings()
            for region in regions:
                candidates.append(
                    CandidateView(
                        id=region["id"],
                        label="Possible question " + region["kind"].split(":", 1)[1],
                        bbox=BoundingBox.model_validate(region["bbox"]),
                    )
                )
            candidates.sort(key=lambda candidate: int(candidate.label.rsplit(" ", 1)[1]))
            dimensions = row["dimensions"]
            result.append(
                PageView(
                    id=row["id"],
                    page_number=row["page_num"],
                    width=dimensions["width"],
                    height=dimensions["height"],
                    rotation=dimensions["rotation"],
                    render_version=RENDER_VERSION,
                    candidates=candidates,
                )
            )
        return AssessmentPages(assessment_id=assessment_id, pages=result)


def page_image(principal: Principal, assessment_id: UUID, page_number: int) -> bytes:
    with Session(engine()) as session, session.begin():
        repo = PrivateRepository(session, principal)
        document = locate(repo, assessment_id, principal)
        repo.object(document)
        row = session.execute(
            text(
                "SELECT image_object_key FROM student_data.document_pages "
                "WHERE document_id=:document "
                "AND student_id=:owner AND page_num=:page "
                "AND dimensions->>'render_version'=:version"
            ),
            {
                "document": document,
                "owner": repo.owner,
                "page": page_number,
                "version": RENDER_VERSION,
            },
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("page_not_found")
        record = repo.object(uuid5(document, f"{RENDER_VERSION}/page/{page_number}"))
        if record.ref.key != row:
            raise LookupError("page_not_found")
        return storage_for(repo.owner).get(record)
