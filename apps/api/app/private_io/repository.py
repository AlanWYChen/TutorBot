from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.identity import Principal
from app.domain.scope import StudentDomain
from app.private_io.types import JobStatus, StoredObject


class PrivateRepository:
    """Request-scoped metadata boundary. No broker calls or infrastructure imports."""

    def __init__(self, session: Session, principal: Principal):
        if not session.in_transaction():
            raise RuntimeError("private IO requires an active transaction")
        self.session = session
        if principal.role == "student":
            self.owner = StudentDomain(session, principal).student_id
            self.schema, self.owner_column = "student_data", "student_id"
        elif principal.role == "admin":
            self.owner = uuid5(NAMESPACE_URL, "tutorbot/admin/" + principal.uid)
            self.schema, self.owner_column = "global_knowledge", "owner_id"
        else:
            raise PermissionError("private_io_denied")

    def register(self, record: StoredObject) -> UUID:
        allowed = (
            {"student-private"}
            if self.schema == "student_data"
            else {"teaching-private", "curriculum-published"}
        )
        if record.ref.owner_id != self.owner or record.ref.bucket not in allowed:
            raise PermissionError("object_scope_denied")
        params = {
            "id": record.ref.resource_id,
            "owner": self.owner,
            "record": record.model_dump_json(),
        }
        self.session.execute(
            text(
                f"INSERT INTO {self.schema}.storage_objects (id,{self.owner_column},record) "
                "VALUES (:id,:owner,CAST(:record AS jsonb)) ON CONFLICT DO NOTHING"
            ),
            params,
        )
        existing = self.object(record.ref.resource_id)
        if existing != record:
            raise ValueError("object_manifest_conflict")
        return record.ref.resource_id

    def object(self, object_id: UUID) -> StoredObject:
        row = self.session.execute(
            text(
                f"SELECT record FROM {self.schema}.storage_objects "
                f"WHERE id=:id AND {self.owner_column}=:owner AND deleted_at IS NULL"
            ),
            {"id": object_id, "owner": self.owner},
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("object_not_found")
        return StoredObject.model_validate(row)

    def tombstone(self, object_id: UUID) -> StoredObject:
        # Return the manifest even on a repeated deletion so physical cleanup can retry.
        row = self.session.execute(
            text(
                f"SELECT record FROM {self.schema}.storage_objects "
                f"WHERE id=:id AND {self.owner_column}=:owner FOR UPDATE"
            ),
            {"id": object_id, "owner": self.owner},
        ).scalar_one_or_none()
        if row is None:
            raise LookupError("object_not_found")
        record = StoredObject.model_validate(row)
        self.session.execute(
            text(
                f"UPDATE {self.schema}.storage_objects SET deleted_at=COALESCE(deleted_at,now()) "
                f"WHERE id=:id AND {self.owner_column}=:owner"
            ),
            {"id": object_id, "owner": self.owner},
        )
        self.session.execute(
            text(
                f"UPDATE {self.schema}.jobs SET state='cancelled',"
                "lease_token=NULL,lease_until=NULL "
                f"WHERE object_id=:id AND {self.owner_column}=:owner "
                "AND state IN ('queued','running','retry_wait')"
            ),
            {"id": object_id, "owner": self.owner},
        )

        return record

    def enqueue(self, object_id: UUID, idempotency_key: str) -> JobStatus:
        if not 1 <= len(idempotency_key) <= 128:
            raise ValueError("invalid_idempotency_key")
        # Lock prevents a concurrent tombstone from allowing a new job afterwards.
        self.session.execute(
            text(
                f"SELECT id FROM {self.schema}.storage_objects WHERE id=:id "
                f"AND {self.owner_column}=:owner FOR UPDATE"
            ),
            {"id": object_id, "owner": self.owner},
        )
        self.object(object_id)
        job_id = uuid4()
        self.session.execute(
            text(
                f"INSERT INTO {self.schema}.jobs "
                f"(id,{self.owner_column},object_id,idempotency_key) "
                "VALUES (:id,:owner,:object,:key) ON CONFLICT DO NOTHING"
            ),
            {"id": job_id, "owner": self.owner, "object": object_id, "key": idempotency_key},
        )
        row = (
            self.session.execute(
                text(
                    f"SELECT * FROM {self.schema}.jobs WHERE {self.owner_column}=:owner "
                    "AND idempotency_key=:key"
                ),
                {"owner": self.owner, "key": idempotency_key},
            )
            .mappings()
            .one()
        )
        if row["object_id"] != object_id:
            raise ValueError("idempotency_conflict")
        return self._status(dict(row))

    @staticmethod
    def _status(row: dict[str, Any]) -> JobStatus:
        return JobStatus(
            id=row["id"], state=row["state"], attempts=row["attempts"], error_code=row["error_code"]
        )

    def status(self, job_id: UUID) -> JobStatus:
        row = (
            self.session.execute(
                text(
                    f"SELECT * FROM {self.schema}.jobs WHERE id=:id AND {self.owner_column}=:owner"
                ),
                {"id": job_id, "owner": self.owner},
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise LookupError("job_not_found")
        return self._status(dict(row))

    def cancel(self, job_id: UUID) -> JobStatus:
        self.status(job_id)
        self.session.execute(
            text(
                f"UPDATE {self.schema}.jobs SET state='cancelled',"
                "lease_token=NULL,lease_until=NULL "
                f"WHERE id=:id AND {self.owner_column}=:owner "
                "AND state IN ('queued','running','retry_wait')"
            ),
            {"id": job_id, "owner": self.owner},
        )
        return self.status(job_id)
