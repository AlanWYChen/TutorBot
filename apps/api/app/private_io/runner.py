from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Engine, text

from app.config import Settings
from app.private_io.storage import GCSObjectStorage
from app.private_io.types import JobPublisher, StorageError, StoredObject


def schema_for(settings: Settings) -> str:
    return "student_data" if settings.service_mode == "runtime" else "global_knowledge"


def require_worker_credentials(settings: Settings) -> None:
    from sqlalchemy.engine import make_url

    if make_url(settings.database_url.get_secret_value()).username != (
        f"tutorbot_{settings.service_mode}_worker"
    ):
        raise ValueError("Worker must use its narrow worker database role")


def relay(engine: Engine, settings: Settings, publisher: JobPublisher) -> int:
    """Jobs are their own transactional outbox. Repeated delivery is deliberate."""
    schema = schema_for(settings)
    with engine.begin() as conn:
        # Recover crashed attempts. A stale worker cannot finish with its old token.
        conn.execute(
            text(f"""
            UPDATE {schema}.jobs SET
              state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'retry_wait' END,
              error_code='worker_lease_expired', lease_token=NULL, lease_until=NULL,
              available_at=now(), dispatched_at=NULL
            WHERE state='running' AND lease_until<now()
        """)
        )
        rows: list[UUID] = list(
            conn.execute(
                text(f"""
            SELECT id FROM {schema}.jobs
            WHERE state IN ('queued','retry_wait') AND available_at<=now()
              AND (dispatched_at IS NULL OR dispatched_at<now()-interval '10 seconds')
            ORDER BY created_at LIMIT 20 FOR UPDATE SKIP LOCKED
        """)
            )
            .scalars()
            .all()
        )
        for job_id in rows:
            # If publish succeeds then DB commit fails, the next pass sends a duplicate.
            # If publish fails, the transaction rolls back and nothing is lost.
            publisher.publish(job_id)
            conn.execute(
                text(f"UPDATE {schema}.jobs SET dispatched_at=now() WHERE id=:id"), {"id": job_id}
            )
    return len(rows)


def claim(engine: Engine, settings: Settings, job_id: UUID) -> dict[str, Any] | None:
    schema = schema_for(settings)
    with engine.begin() as conn:
        row = (
            conn.execute(
                text(f"""
            UPDATE {schema}.jobs SET state='running',attempts=attempts+1,
                lease_token=:token,lease_until=now()+
                    CASE WHEN kind='render_document' THEN interval '360 seconds'
                    ELSE interval '120 seconds' END
            WHERE id=:id AND state IN ('queued','retry_wait') AND available_at<=now()
                AND attempts<3
            RETURNING *
        """),
                {"id": job_id, "token": uuid4()},
            )
            .mappings()
            .one_or_none()
        )
        return dict(row) if row else None


def finish(engine: Engine, settings: Settings, job: dict[str, Any], error: str | None) -> None:
    state = "succeeded" if error is None else ("failed" if job["attempts"] >= 3 else "retry_wait")
    # Missing/deleted or integrity-conflicting source is permanent, not a retry storm.
    if error in {
        "object_not_found",
        "object_integrity_failed",
        "object_version_changed",
        "render_limit_or_invalid_pdf",
        "render_manifest_conflict",
        "unsupported_job",
    }:
        state = "failed"
    with engine.begin() as conn:
        conn.execute(
            text(f"""
            UPDATE {schema_for(settings)}.jobs SET state=:state,error_code=:error,
                lease_token=NULL,lease_until=NULL,dispatched_at=NULL,
                available_at=now()+interval '2 seconds'
            WHERE id=:id AND state='running' AND lease_token=:token AND lease_until>now()
        """),
            {"id": job["id"], "token": job["lease_token"], "state": state, "error": error},
        )


def run_job(engine: Engine, settings: Settings, job_id: UUID) -> None:
    job = claim(engine, settings, job_id)
    if job is None:
        return
    error = None
    try:
        with engine.connect() as conn:
            record_json = conn.execute(
                text(
                    f"SELECT record FROM {schema_for(settings)}.storage_objects "
                    "WHERE id=:id AND deleted_at IS NULL"
                ),
                {"id": job["object_id"]},
            ).scalar_one_or_none()
        if record_json is None:
            raise StorageError("object_not_found")
        record = StoredObject.model_validate(record_json)
        # Handler is replay-safe: reads and verifies immutable source, no derived writes.
        data = GCSObjectStorage(settings, record.ref.owner_id).get(record)
        if job["kind"] == "render_document":
            from app.assessments.rendering import render_document

            render_document(engine, settings, job, record, data)
    except StorageError as exc:
        error = str(exc)
    except Exception:
        error = "worker_unavailable"
    finish(engine, settings, job, error)
