from datetime import datetime
from typing import Literal, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.limits import MAX_UPLOAD_BYTES

Bucket = Literal["student-private", "curriculum-published", "teaching-private"]
JobState = Literal["queued", "running", "retry_wait", "succeeded", "failed", "cancelled"]


class ObjectRef(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    bucket: Bucket
    owner_id: UUID
    resource_id: UUID
    assessment_id: UUID | None = None

    @property
    def key(self) -> str:
        assessment = str(self.assessment_id) if self.assessment_id else "unassigned"
        return f"{self.owner_id}/{assessment}/{self.resource_id}"


class StoredObject(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    ref: ObjectRef
    sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    media_type: Literal["application/pdf", "image/png", "image/jpeg", "text/plain"]
    size_bytes: int = Field(gt=0, le=MAX_UPLOAD_BYTES)
    generation: int = Field(gt=0)
    retention_until: datetime


class JobStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: UUID
    state: JobState
    attempts: int
    error_code: str | None = None


class StorageError(Exception):
    """Sanitized boundary error; never contains object content or provider responses."""


class ObjectStorage(Protocol):
    def put(self, ref: ObjectRef, data: bytes, media_type: str) -> StoredObject: ...
    def get(self, record: StoredObject) -> bytes: ...
    def delete(self, record: StoredObject) -> None: ...
    def signed_access(self, record: StoredObject, ttl_seconds: int = 300) -> str: ...


class JobDispatcher(Protocol):
    def enqueue(self, object_id: UUID, idempotency_key: str) -> JobStatus: ...
    def status(self, job_id: UUID) -> JobStatus: ...
    def cancel(self, job_id: UUID) -> JobStatus: ...


class JobPublisher(Protocol):
    def publish(self, job_id: UUID) -> None: ...
