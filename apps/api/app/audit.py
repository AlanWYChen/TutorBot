import logging
import logging.config
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict
from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.students.models import Base

Route = Literal[
    "/v1/auth/me",
    "/v1/student/account",
    "/v1/student/accounts/{account_id}",
    "/v1/admin/access",
    "/v1/admin/audit",
    "/v1/admin/studio/sources",
    "/v1/admin/studio/sources/{document_id}",
    "/v1/admin/studio/sources/{document_id}/restore",
    "/v1/admin/studio/sources/{document_id}/pages/{number}",
    "/v1/admin/studio/sources/{document_id}/pages/{number}/restore",
    "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}/restore",
    "/v1/admin/studio/datasets/{dataset_id}/cases/{case_id}/annotation",

    "/v1/admin/studio/datasets",
    "/v1/admin/studio/datasets/{dataset_id}/cases",
    "/v1/admin/studio/datasets/{dataset_id}/export",
    "/v1/admin/studio/datasets/{dataset_id}/import",
    "/v1/admin/studio/datasets/{dataset_id}/cases/{case_id}/review",
    "/v1/admin/studio/datasets/{dataset_id}/cases/{case_id}/crop",
    "/v1/admin/studio/sources/{document_id}/render",
    "/v1/admin/studio/sources/{document_id}/pages",
    "/v1/admin/studio/sources/{document_id}/pages/{number}/image",
    "/v1/admin/studio/sources/{document_id}/annotations",
    "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}",
    "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}/crop",
    "/v1/student/assessments/upload",
    "/v1/student/assessments",
    "/v1/student/assessments/{assessment_id}/render",
    "/v1/student/assessments/{assessment_id}/pages",
    "/v1/student/assessments/{assessment_id}/pages/{page_number}/image",
    "/v1/student/assessments/{resource_id}/file",
    "/v1/student/assessments/{resource_id}/status",
    "/v1/admin/knowledge/upload",
    "/v1/admin/knowledge/{resource_id}/file",
    "/v1/admin/knowledge/{resource_id}/status",
    "unmatched",
]
ROUTES = {
    "/v1/auth/me",
    "/v1/student/account",
    "/v1/student/accounts/{account_id}",
    "/v1/admin/access",
    "/v1/admin/audit",
    "/v1/admin/studio/sources",
    "/v1/admin/studio/sources/{document_id}",
    "/v1/admin/studio/sources/{document_id}/restore",
    "/v1/admin/studio/sources/{document_id}/pages/{number}",
    "/v1/admin/studio/sources/{document_id}/pages/{number}/restore",
    "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}/restore",
    "/v1/admin/studio/datasets/{dataset_id}/cases/{case_id}/annotation",

    "/v1/admin/studio/datasets",
    "/v1/admin/studio/datasets/{dataset_id}/cases",
    "/v1/admin/studio/datasets/{dataset_id}/export",
    "/v1/admin/studio/datasets/{dataset_id}/import",
    "/v1/admin/studio/datasets/{dataset_id}/cases/{case_id}/review",
    "/v1/admin/studio/datasets/{dataset_id}/cases/{case_id}/crop",
    "/v1/admin/studio/sources/{document_id}/render",
    "/v1/admin/studio/sources/{document_id}/pages",
    "/v1/admin/studio/sources/{document_id}/pages/{number}/image",
    "/v1/admin/studio/sources/{document_id}/annotations",
    "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}",
    "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}/crop",
    "/v1/student/assessments/upload",
    "/v1/student/assessments",
    "/v1/student/assessments/{assessment_id}/render",
    "/v1/student/assessments/{assessment_id}/pages",
    "/v1/student/assessments/{assessment_id}/pages/{page_number}/image",
    "/v1/student/assessments/{resource_id}/file",
    "/v1/student/assessments/{resource_id}/status",
    "/v1/admin/knowledge/upload",
    "/v1/admin/knowledge/{resource_id}/file",
    "/v1/admin/knowledge/{resource_id}/status",
}


class SafeEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: UUID
    service: Literal["runtime", "admin"]
    action: Literal["http_request", "audit_unavailable"]
    route: Route
    status_code: int
    outcome: Literal["success", "denied", "error"]


def configure_logging() -> None:
    logging.config.dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": True,
            "handlers": {
                "safe": {"class": "logging.StreamHandler", "formatter": "message"},
                "discard": {"class": "logging.NullHandler"},
            },
            "formatters": {"message": {"format": "%(message)s"}},
            "root": {"handlers": ["discard"], "level": "CRITICAL"},
            "loggers": {
                "tutorbot.events": {"handlers": ["safe"], "level": "INFO", "propagate": False}
            },
        }
    )


def log_event(event: SafeEvent) -> None:
    logging.getLogger("tutorbot.events").info(event.model_dump_json())


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __mapper_args__ = {"eager_defaults": False}
    id: Mapped[UUID] = mapped_column(primary_key=True)
    actor_uid: Mapped[str | None] = mapped_column(String(128))
    actor_role: Mapped[str | None] = mapped_column(String(16))
    action: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(128))
    method: Mapped[str] = mapped_column(String(8))
    status_code: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(16))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
