import json
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from uuid import uuid5

from sqlalchemy import Engine, text

from app.assessments.types import RENDER_VERSION, RenderResult
from app.config import Settings
from app.private_io.storage import GCSObjectStorage
from app.private_io.types import ObjectRef, StorageError, StoredObject


def render_to_directory(data: bytes, output: Path) -> RenderResult:
    try:
        result = subprocess.run(
            [sys.executable, "-m", "app.assessments.render_pdf", str(output)],
            input=data,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=65,
            check=True,
            env={"PYTHONDONTWRITEBYTECODE": "1"},
        )
        if len(result.stdout) > 256 * 1024:
            raise ValueError
        rendered = RenderResult.model_validate_json(result.stdout)
        if [page.page_number for page in rendered.pages] != list(range(1, len(rendered.pages) + 1)):
            raise ValueError
        return rendered
    except Exception:
        raise StorageError("render_limit_or_invalid_pdf") from None


def active(engine: Engine, job: dict[str, Any], schema: str = "student_data") -> bool:
    with engine.connect() as conn:
        return bool(
            conn.scalar(
                text(
                    f"SELECT 1 FROM {schema}.jobs WHERE id=:id AND state='running' "
                    "AND lease_token=:token AND lease_until>now()"
                ),
                {"id": job["id"], "token": job["lease_token"]},
            )
        )


def render_document(
    engine: Engine, settings: Settings, job: dict[str, Any], source: StoredObject, data: bytes
) -> None:
    schema = "student_data" if settings.service_mode == "runtime" else "global_knowledge"
    owner_column = "student_id" if settings.service_mode == "runtime" else "owner_id"
    owned_column = ",student_id" if settings.service_mode == "runtime" else ""
    owned_value = ",:owner" if settings.service_mode == "runtime" else ""
    scope_predicate = "AND student_id=:owner " if settings.service_mode == "runtime" else ""
    if source.media_type != "application/pdf":
        raise StorageError("unsupported_job")
    store = GCSObjectStorage(settings, source.ref.owner_id)
    records: list[StoredObject] = []
    with TemporaryDirectory(prefix="tutorbot-render-") as directory:
        output = Path(directory)
        rendered = render_to_directory(data, output)
        for page in rendered.pages:
            if not active(engine, job, schema):
                return
            image_id = uuid5(source.ref.resource_id, f"{RENDER_VERSION}/page/{page.page_number}")
            ref = ObjectRef(
                bucket="student-private"
                if settings.service_mode == "runtime"
                else "teaching-private",
                owner_id=source.ref.owner_id,
                resource_id=image_id,
                assessment_id=source.ref.assessment_id,
            )
            record = store.put(
                ref,
                (output / f"page-{page.page_number}.png").read_bytes(),
                "image/png",
                retention_until=source.retention_until,
            )
            records.append(record)
        # Publish all pages/candidates atomically, under the job and source fences.
        # External immutable writes can be repeated; uncommitted objects are unservable.
        with engine.begin() as conn:
            current = conn.scalar(
                text(
                    f"SELECT id FROM {schema}.jobs WHERE id=:id AND state='running' "
                    "AND lease_token=:token AND lease_until>now() FOR UPDATE"
                ),
                {"id": job["id"], "token": job["lease_token"]},
            )
            source_live = conn.scalar(
                text(
                    f"SELECT id FROM {schema}.storage_objects WHERE id=:id AND deleted_at IS NULL"
                ),
                {"id": source.ref.resource_id},
            )
            if current is None or source_live is None:
                return
            for page, record in zip(rendered.pages, records, strict=True):
                conn.execute(
                    text(
                        f"INSERT INTO {schema}.storage_objects (id,{owner_column},record) "
                        "VALUES (:id,:owner,CAST(:record AS jsonb)) ON CONFLICT DO NOTHING"
                    ),
                    {
                        "id": record.ref.resource_id,
                        "owner": source.ref.owner_id,
                        "record": record.model_dump_json(),
                    },
                )
                stored = conn.scalar(
                    text(
                        f"SELECT record FROM {schema}.storage_objects "
                        "WHERE id=:id AND deleted_at IS NULL"
                    ),
                    {"id": record.ref.resource_id},
                )
                if stored is None or StoredObject.model_validate(stored) != record:
                    raise StorageError("render_manifest_conflict")
                page_id = uuid5(record.ref.resource_id, "page-row")
                dimensions = {
                    "width": page.width,
                    "height": page.height,
                    "rotation": page.rotation,
                    "render_version": RENDER_VERSION,
                }
                conn.execute(
                    text(
                        f"INSERT INTO {schema}.document_pages "
                        f"(id{owned_column},document_id,page_num,dimensions,image_object_key) "
                        f"VALUES (:id{owned_value},:document,:page,"
                        "CAST(:dimensions AS jsonb),:key) "
                        "ON CONFLICT DO NOTHING"
                    ),
                    {
                        "id": page_id,
                        "owner": source.ref.owner_id,
                        "document": source.ref.resource_id,
                        "page": page.page_number,
                        "dimensions": json.dumps(dimensions),
                        "key": record.ref.key,
                    },
                )
                saved_page = conn.execute(
                    text(
                        f"SELECT id,dimensions,image_object_key FROM {schema}.document_pages "
                        f"WHERE document_id=:document {scope_predicate}AND page_num=:page"
                    ),
                    {
                        "owner": source.ref.owner_id,
                        "document": source.ref.resource_id,
                        "page": page.page_number,
                    },
                ).one()
                if saved_page != (page_id, dimensions, record.ref.key):
                    raise StorageError("render_manifest_conflict")
                for index, candidate in enumerate(page.candidates):
                    conn.execute(
                        text(
                            f"INSERT INTO {schema}.document_regions "
                            f"(id{owned_column},page_id,bbox,kind,extraction_confidence) "
                            f"VALUES (:id{owned_value},:page,CAST(:box AS jsonb),:kind,0.5) "
                            "ON CONFLICT DO NOTHING"
                        ),
                        {
                            "id": uuid5(page_id, f"candidate/{index}"),
                            "owner": source.ref.owner_id,
                            "page": page_id,
                            "box": candidate.bbox.model_dump_json(),
                            "kind": f"question_candidate:{candidate.number}",
                        },
                    )
            # Atomic completion avoids a crash publishing pages but leaving a running job.
            conn.execute(
                text(
                    f"UPDATE {schema}.jobs SET state='succeeded',error_code=NULL,"
                    "lease_token=NULL,lease_until=NULL WHERE id=:id AND lease_token=:token"
                ),
                {"id": job["id"], "token": job["lease_token"]},
            )
