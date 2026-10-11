import os
import time
from uuid import uuid4

import pytest
from pydantic import SecretStr
from sqlalchemy import create_engine, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.auth.identity import Principal
from app.config import Settings
from app.private_io.repository import PrivateRepository
from app.private_io.runner import claim, finish, relay, run_job
from app.private_io.storage import GCSObjectStorage
from app.private_io.types import ObjectRef, StorageError

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_PRIVATE_IO_INTEGRATION") != "1",
    reason="Requires local DB, GCS, Redis and workers",
)


def engines():
    runtime = create_engine(
        Settings().database_url.get_secret_value().replace("postgresql://", "postgresql+psycopg://")
    )
    worker = create_engine(
        os.environ["RUNTIME_WORKER_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
    )
    return runtime, worker


def setup_object(runtime):
    principal = Principal(uid="private-io-test-" + uuid4().hex, role="student")
    with Session(runtime) as session, session.begin():
        repo = PrivateRepository(session, principal)
        store = GCSObjectStorage(Settings(), repo.owner)
        ref = ObjectRef(
            bucket="student-private",
            owner_id=repo.owner,
            resource_id=uuid4(),
            assessment_id=uuid4(),
        )
        obj = store.put(ref, b"synthetic private storage fixture", "text/plain")
        repo.register(obj)
    return principal, store, obj


def test_real_storage_manifest_and_tenant_boundaries():
    runtime, worker = engines()
    principal, store, obj = setup_object(runtime)
    assert store.get(obj) == b"synthetic private storage fixture"
    assert store.put(obj.ref, b"synthetic private storage fixture", "text/plain") == obj
    with pytest.raises(StorageError, match="object_conflict"):
        store.put(obj.ref, b"different synthetic content", "text/plain")
    with Session(runtime) as session, session.begin():
        repo = PrivateRepository(session, principal)
        assert repo.object(obj.ref.resource_id) == obj
        job = repo.enqueue(obj.ref.resource_id, "verify-1")
        assert repo.enqueue(obj.ref.resource_id, "verify-1").id == job.id
    other = Principal(uid="private-io-other-" + uuid4().hex, role="student")
    with Session(runtime) as session, session.begin():
        repo = PrivateRepository(session, other)
        with pytest.raises(LookupError):
            repo.object(obj.ref.resource_id)
        with pytest.raises(LookupError):
            repo.status(job.id)
    with runtime.connect() as conn:
        assert conn.scalar(text("SELECT count(*) FROM student_data.storage_objects")) == 0
    with pytest.raises(DBAPIError), worker.begin() as conn:
        conn.execute(text("SELECT * FROM student_data.tutoring_messages"))
    with pytest.raises(DBAPIError), worker.begin() as conn:
        conn.execute(text("SELECT * FROM global_knowledge.jobs"))
    with Session(runtime) as session, session.begin():
        repo = PrivateRepository(session, principal)
        assert repo.cancel(job.id).state == "cancelled"
        assert repo.tombstone(obj.ref.resource_id) == obj
        assert repo.tombstone(obj.ref.resource_id) == obj
    store.delete(obj)
    store.delete(obj)
    with pytest.raises(StorageError, match="not_found"):
        store.get(obj)
    runtime.dispose()
    worker.dispose()


def test_real_celery_worker_completes_durable_job():
    runtime, worker = engines()
    principal, store, obj = setup_object(runtime)
    with Session(runtime) as session, session.begin():
        repo = PrivateRepository(session, principal)
        job = repo.enqueue(obj.ref.resource_id, "celery-delivery")
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        with Session(runtime) as session, session.begin():
            status = PrivateRepository(session, principal).status(job.id)
        if status.state in {"succeeded", "failed"}:
            break
        time.sleep(0.3)
    assert status.state == "succeeded"
    assert status.attempts == 1
    # A new transport delivery has no additional effects or attempt.
    settings = Settings(database_url=SecretStr(os.environ["RUNTIME_WORKER_DATABASE_URL"]))
    run_job(worker, settings, job.id)
    with Session(runtime) as session, session.begin():
        repo = PrivateRepository(session, principal)
        assert repo.status(job.id).attempts == 1
        repo.tombstone(obj.ref.resource_id)
    store.delete(obj)
    runtime.dispose()
    worker.dispose()


def test_retry_recovery_fencing_and_cancel(monkeypatch):
    runtime, worker = engines()
    principal, store, obj = setup_object(runtime)
    settings = Settings(database_url=SecretStr(os.environ["RUNTIME_WORKER_DATABASE_URL"]))
    # Keep relay from consuming this test's jobs while testing state transitions.
    with Session(runtime) as session, session.begin():
        repo = PrivateRepository(session, principal)
        job = repo.enqueue(obj.ref.resource_id, "fenced-attempt")
        session.execute(
            text("UPDATE student_data.jobs SET dispatched_at=now() WHERE id=:id"), {"id": job.id}
        )
    first = claim(worker, settings, job.id)
    assert first and first["attempts"] == 1
    assert claim(worker, settings, job.id) is None
    with worker.begin() as conn:
        conn.execute(
            text("UPDATE student_data.jobs SET lease_until=now()-interval '1 second' WHERE id=:id"),
            {"id": job.id},
        )

    class Capture:
        def publish(self, job_id):
            pass

    relay(worker, settings, Capture())
    second = claim(worker, settings, job.id)
    assert second and second["attempts"] == 2
    finish(worker, settings, first, None)
    with Session(runtime) as session, session.begin():
        repo = PrivateRepository(session, principal)
        assert repo.status(job.id).state == "running"
        assert repo.cancel(job.id).state == "cancelled"
    finish(worker, settings, second, None)
    with Session(runtime) as session, session.begin():
        repo = PrivateRepository(session, principal)
        assert repo.status(job.id).state == "cancelled"
        retry = repo.enqueue(obj.ref.resource_id, "bounded-retry")
        session.execute(
            text("UPDATE student_data.jobs SET dispatched_at=now() WHERE id=:id"), {"id": retry.id}
        )

    def unavailable(*args):
        raise StorageError("storage_unavailable")

    monkeypatch.setattr(GCSObjectStorage, "get", unavailable)
    for attempt in range(1, 4):
        run_job(worker, settings, retry.id)
        with worker.begin() as conn:
            row = conn.execute(
                text("SELECT attempts,state FROM student_data.jobs WHERE id=:id"), {"id": retry.id}
            ).one()
            assert row == (attempt, "failed" if attempt == 3 else "retry_wait")
            conn.execute(
                text(
                    "UPDATE student_data.jobs SET available_at=now(),dispatched_at=now() "
                    "WHERE id=:id"
                ),
                {"id": retry.id},
            )
    with Session(runtime) as session, session.begin():
        PrivateRepository(session, principal).tombstone(obj.ref.resource_id)
    store.delete(obj)
    runtime.dispose()
    worker.dispose()


def test_admin_storage_and_jobs_are_separate():
    admin = create_engine(
        os.environ["ADMIN_DATABASE_URL"].replace("postgresql://", "postgresql+psycopg://")
    )
    principal = Principal(uid="synthetic-maintainer", role="admin")
    with Session(admin) as session, session.begin():
        repo = PrivateRepository(session, principal)
        store = GCSObjectStorage(Settings(service_mode="admin"), repo.owner)
        obj = store.put(
            ObjectRef(bucket="teaching-private", owner_id=repo.owner, resource_id=uuid4()),
            b"synthetic admin fixture",
            "text/plain",
        )
        repo.register(obj)
        job = repo.enqueue(obj.ref.resource_id, "admin-" + uuid4().hex)
    settings = Settings(
        service_mode="admin", database_url=SecretStr(os.environ["ADMIN_WORKER_DATABASE_URL"])
    )
    worker = create_engine(
        settings.database_url.get_secret_value().replace("postgresql://", "postgresql+psycopg://")
    )
    run_job(worker, settings, job.id)
    with Session(admin) as session, session.begin():
        repo = PrivateRepository(session, principal)
        assert repo.status(job.id).state == "succeeded"
        repo.tombstone(obj.ref.resource_id)
    with pytest.raises(DBAPIError), worker.begin() as conn:
        conn.execute(text("SELECT * FROM student_data.storage_objects"))
    store.delete(obj)
    admin.dispose()
    worker.dispose()
