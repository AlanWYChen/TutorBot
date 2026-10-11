import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any, cast
from uuid import UUID

from google.api_core.exceptions import NotFound, PreconditionFailed
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage  # type: ignore[import-untyped]

from app.config import Settings
from app.limits import MAX_UPLOAD_BYTES
from app.private_io.types import ObjectRef, StorageError, StoredObject


class GCSObjectStorage:
    """GCS SDK in both environments; caller binds a server-resolved owner and service.

    Cloud bucket IAM must independently enforce the service split. Published object
    references must come from a published DB view, never directly from a request.
    """

    def __init__(self, settings: Settings, owner_id: UUID, client: Any = None):
        self.settings = settings
        self.owner_id = owner_id
        self.client = client or storage.Client(
            project=settings.google_cloud_project,
            credentials=(
                AnonymousCredentials()  # type: ignore[no-untyped-call]
                if settings.storage_emulator_host
                else None
            ),
            client_options=(
                {"api_endpoint": settings.storage_emulator_host}
                if settings.storage_emulator_host
                else None
            ),
        )

    def _blob(self, ref: ObjectRef, *, write: bool = False) -> Any:
        if ref.bucket == "student-private":
            allowed = self.settings.service_mode == "runtime" and ref.owner_id == self.owner_id
        elif ref.bucket == "teaching-private":
            allowed = self.settings.service_mode == "admin" and ref.owner_id == self.owner_id
        else:
            allowed = not write or (
                self.settings.service_mode == "admin" and ref.owner_id == self.owner_id
            )
        if not allowed:
            raise StorageError("storage_scope_denied")
        bucket_name = {
            "student-private": self.settings.student_private_bucket,
            "curriculum-published": self.settings.curriculum_published_bucket,
            "teaching-private": self.settings.teaching_private_bucket,
        }[ref.bucket]
        return self.client.bucket(bucket_name).blob(ref.key)

    def put(self, ref: ObjectRef, data: bytes, media_type: str) -> StoredObject:
        if media_type not in {"application/pdf", "image/png", "image/jpeg", "text/plain"}:
            raise StorageError("unsupported_media_type")
        if not 0 < len(data) <= MAX_UPLOAD_BYTES:
            raise StorageError("invalid_object_size")
        digest = hashlib.sha256(data).hexdigest()
        retention = datetime.now(UTC) + timedelta(days=self.settings.object_retention_days)
        blob = self._blob(ref, write=True)
        blob.metadata = {"sha256": digest, "retention_until": retention.isoformat()}
        try:
            try:
                blob.upload_from_string(
                    data,
                    content_type=media_type,
                    if_generation_match=0,
                    checksum="crc32c",
                    timeout=30,
                )
            except PreconditionFailed:
                # Lost acknowledgements cannot overwrite evidence.
                blob.reload(timeout=30)
                if (blob.metadata or {}).get("sha256") != digest or blob.content_type != media_type:
                    raise StorageError("object_conflict") from None
                if int(blob.size) != len(data):
                    raise StorageError("object_conflict") from None
                retention = datetime.fromisoformat(blob.metadata["retention_until"])
        except StorageError:
            raise
        except Exception:
            raise StorageError("storage_unavailable") from None
        return StoredObject(
            ref=ref,
            sha256=digest,
            media_type=media_type,  # type: ignore[arg-type]
            size_bytes=len(data),
            generation=int(blob.generation),
            retention_until=retention,
        )

    def get(self, record: StoredObject) -> bytes:
        blob = self._blob(record.ref)
        try:
            data = cast(
                bytes,
                blob.download_as_bytes(
                    if_generation_match=record.generation,
                    checksum="crc32c",
                    timeout=30,
                    start=0,
                    end=record.size_bytes,
                ),
            )
        except NotFound:
            raise StorageError("object_not_found") from None
        except PreconditionFailed:
            raise StorageError("object_version_changed") from None
        except Exception:
            raise StorageError("storage_unavailable") from None
        if len(data) != record.size_bytes or hashlib.sha256(data).hexdigest() != record.sha256:
            raise StorageError("object_integrity_failed")
        return data

    def delete(self, record: StoredObject) -> None:
        blob = self._blob(record.ref, write=True)
        try:
            blob.delete(if_generation_match=record.generation, timeout=30)
        except NotFound:
            return
        except PreconditionFailed:
            raise StorageError("object_version_changed") from None
        except Exception:
            raise StorageError("storage_unavailable") from None

    def signed_access(self, record: StoredObject, ttl_seconds: int = 300) -> str:
        blob = self._blob(record.ref)
        if not 1 <= ttl_seconds <= 900:
            raise StorageError("invalid_access_ttl")
        if self.settings.storage_emulator_host:
            raise StorageError("signed_access_requires_real_gcs")
        try:
            return cast(
                str,
                blob.generate_signed_url(
                    version="v4",
                    expiration=timedelta(seconds=ttl_seconds),
                    method="GET",
                    query_parameters={"generation": str(record.generation)},
                ),
            )
        except Exception:
            raise StorageError("storage_signing_unavailable") from None
