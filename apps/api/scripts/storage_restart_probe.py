"""Synthetic restart gate. DB manifest is the sole source for resumed object reads."""

import sys
import time
from uuid import NAMESPACE_URL, uuid5

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.auth.identity import Principal
from app.config import Settings
from app.db import engine
from app.private_io.repository import PrivateRepository
from app.private_io.storage import GCSObjectStorage
from app.private_io.types import ObjectRef, StorageError, StoredObject

settings = Settings()
if settings.app_env != "local" or not settings.storage_emulator_host:
    raise RuntimeError("Restart probe requires local emulators")
principal = Principal(uid="synthetic-private-io-restart", role="student")
object_id = uuid5(NAMESPACE_URL, "tutorbot/p007/restart/" + sys.argv[2])
with Session(engine()) as session, session.begin():
    repo = PrivateRepository(session, principal)
    store = GCSObjectStorage(settings, repo.owner)
    if sys.argv[1] == "deleted":
        row = session.execute(
            text(
                "SELECT record FROM student_data.storage_objects "
                "WHERE id=:id AND student_id=:owner AND deleted_at IS NOT NULL"
            ),
            {"id": object_id, "owner": repo.owner},
        ).scalar_one()
        obj = StoredObject.model_validate(row)
        try:
            store.get(obj)
        except StorageError as exc:
            assert str(exc) == "object_not_found"
        else:
            raise AssertionError("Deleted object returned after restart")
    elif sys.argv[1] == "prepare":
        obj = store.put(
            ObjectRef(bucket="student-private", owner_id=repo.owner, resource_id=object_id),
            b"synthetic restart fixture",
            "text/plain",
        )
        repo.register(obj)
        assert repo.enqueue(object_id, "restart-" + sys.argv[2]).state == "queued"
    else:
        obj = repo.object(object_id)
        assert store.get(obj) == b"synthetic restart fixture"
        if sys.argv[1] == "check":
            job = repo.enqueue(object_id, "restart-" + sys.argv[2])
            deadline = time.monotonic() + 30
            while repo.status(job.id).state not in {"succeeded", "failed"}:
                if time.monotonic() > deadline:
                    raise AssertionError("Durable job did not resume after restart")
                time.sleep(0.3)
            assert repo.status(job.id).state == "succeeded"
        if sys.argv[1] == "cleanup":
            repo.tombstone(object_id)
if sys.argv[1] == "cleanup":
    store.delete(obj)
    store.delete(obj)
    try:
        store.get(obj)
    except StorageError as exc:
        assert str(exc) == "object_not_found"
    else:
        raise AssertionError("Object still present after deletion")
print("Synthetic storage restart phase passed: " + sys.argv[1])
