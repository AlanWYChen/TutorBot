import base64
import json
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from google.api_core.exceptions import PreconditionFailed

from app.config import Settings
from app.private_io.cloud import CloudRunJobsPublisher, CloudTasksPublisher, CloudTasksTarget
from app.private_io.storage import GCSObjectStorage
from app.private_io.types import ObjectRef, StorageError, StoredObject


def record() -> StoredObject:
    import hashlib

    return StoredObject(
        ref=ObjectRef(bucket="student-private", owner_id=uuid4(), resource_id=uuid4()),
        sha256=hashlib.sha256(b"synthetic").hexdigest(),
        size_bytes=9,
        generation=4,
        media_type="text/plain",
        retention_until=datetime.now(UTC) + timedelta(days=30),
    )


def test_storage_guards_and_integrity() -> None:
    obj = record()
    client = MagicMock()
    blob = client.bucket.return_value.blob.return_value
    blob.download_as_bytes.return_value = b"synthetic"
    adapter = GCSObjectStorage(Settings(app_env="test"), obj.ref.owner_id, client)
    assert adapter.get(obj) == b"synthetic"
    assert blob.download_as_bytes.call_args.kwargs["if_generation_match"] == 4
    blob.download_as_bytes.return_value = b"corrupt!!"
    with pytest.raises(StorageError, match="integrity_failed"):
        adapter.get(obj)
    with pytest.raises(StorageError, match="scope_denied"):
        GCSObjectStorage(Settings(app_env="test"), uuid4(), client).get(obj)
    with pytest.raises(StorageError, match="scope_denied"):
        GCSObjectStorage(
            Settings(app_env="test", service_mode="admin"), obj.ref.owner_id, client
        ).get(obj)
    blob.download_as_bytes.side_effect = RuntimeError("SECRET provider content")
    with pytest.raises(StorageError, match="^storage_unavailable$"):
        adapter.get(obj)


def test_storage_retry_cannot_overwrite() -> None:
    obj = record()
    client = MagicMock()
    blob = client.bucket.return_value.blob.return_value
    blob.upload_from_string.side_effect = PreconditionFailed("exists")
    blob.content_type, blob.size, blob.generation = "text/plain", 9, 4
    adapter = GCSObjectStorage(Settings(app_env="test"), obj.ref.owner_id, client)
    # SDK reload preserves these fixture metadata values after attempted upload.
    blob.reload.side_effect = lambda **kw: setattr(
        blob, "metadata", {"sha256": obj.sha256, "retention_until": obj.retention_until.isoformat()}
    )
    assert adapter.put(obj.ref, b"synthetic", "text/plain") == obj
    assert blob.upload_from_string.call_args.kwargs["if_generation_match"] == 0
    with pytest.raises(StorageError, match="object_conflict"):
        adapter.put(obj.ref, b"different", "text/plain")


def test_signed_access_bounded_and_local_refusal(monkeypatch: pytest.MonkeyPatch) -> None:
    obj, client = record(), MagicMock()
    adapter = GCSObjectStorage(
        Settings(app_env="test", storage_emulator_host="http://storage:4443"),
        obj.ref.owner_id,
        client,
    )
    with pytest.raises(StorageError, match="requires_real_gcs"):
        adapter.signed_access(obj)
    with pytest.raises(ValueError, match="Storage emulator"):
        Settings(app_env="production", storage_emulator_host="http://storage:4443")
    monkeypatch.delenv("STORAGE_EMULATOR_HOST", raising=False)
    adapter = GCSObjectStorage(Settings(app_env="production"), obj.ref.owner_id, client)
    client.bucket.return_value.blob.return_value.generate_signed_url.return_value = "https://signed"
    assert adapter.signed_access(obj, 60) == "https://signed"
    with pytest.raises(StorageError, match="invalid_access_ttl"):
        adapter.signed_access(obj, 901)
    kwargs = client.bucket.return_value.blob.return_value.generate_signed_url.call_args.kwargs
    assert kwargs["version"] == "v4" and kwargs["query_parameters"] == {"generation": "4"}


def test_cloud_contracts_only_dispatch_fixed_job_reference() -> None:
    job_id, transport = uuid4(), MagicMock()
    target = CloudTasksTarget(
        project="tutorbot-staging",
        location="us-central1",
        queue="runtime",
        worker_url="https://worker.run.app/jobs",
        audience="https://worker.run.app",
        service_account_email="tasks@tutorbot-staging.iam.gserviceaccount.com",
    )
    CloudTasksPublisher(target, transport).publish(job_id)
    url, payload = transport.post_json.call_args.args
    assert url.endswith("/queues/runtime/tasks")
    request = payload["task"]["httpRequest"]
    assert json.loads(base64.b64decode(request["body"])) == {"job_id": str(job_id)}
    assert request["oidcToken"]["audience"] == target.audience
    with pytest.raises(ValueError):
        target.model_copy(update={"worker_url": "http://localhost"}).validate_target()
    CloudRunJobsPublisher(
        "projects/tutorbot-staging/locations/us-central1/jobs/runtime", transport
    ).publish(job_id)
    url, payload = transport.post_json.call_args.args
    assert url.endswith("/jobs/runtime:run")
    assert payload["overrides"]["containerOverrides"][0]["env"] == [
        {"name": "TUTORBOT_JOB_ID", "value": str(job_id)}
    ]
    with pytest.raises(ValueError):
        CloudRunJobsPublisher("projects/p/locations/l/jobs/j?injected=1", transport)
