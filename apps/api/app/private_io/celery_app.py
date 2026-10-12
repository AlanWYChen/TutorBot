from pathlib import Path
from typing import Any
from uuid import UUID

from celery import Celery  # type: ignore[import-untyped]
from celery.signals import heartbeat_sent, worker_ready  # type: ignore[import-untyped]
from sqlalchemy import text

from app.config import Settings
from app.db import engine
from app.private_io.runner import require_worker_credentials, run_job

settings = Settings()
celery_app = Celery("tutorbot", broker=settings.redis_url)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_ignore_result=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_time_limit=300,
    task_soft_time_limit=280,
    task_default_queue=f"tutorbot-{settings.service_mode}",
    broker_transport_options={"visibility_timeout": 360},
    worker_hijack_root_logger=False,
    worker_redirect_stdouts=False,
    worker_enable_remote_control=False,
    task_send_sent_event=False,
)


@celery_app.task(name="tutorbot.verify_object")  # type: ignore[misc]
def verify_object(job_id: str) -> None:
    require_worker_credentials(settings)
    run_job(engine(), settings, UUID(job_id))


class CeleryPublisher:
    def publish(self, job_id: UUID) -> None:
        celery_app.send_task(
            "tutorbot.verify_object",
            args=[str(job_id)],
            queue=f"tutorbot-{settings.service_mode}",
            argsrepr="[private job reference]",
            kwargsrepr="{}",
        )


# Readiness is emitted only after the worker has connected to its limited DB role.
_ready = False


@worker_ready.connect  # type: ignore[misc]
def mark_ready(**kwargs: Any) -> None:
    global _ready
    require_worker_credentials(settings)
    schema = "student_data" if settings.service_mode == "runtime" else "global_knowledge"
    with engine().connect() as connection:
        connection.execute(text(f"SELECT id FROM {schema}.jobs LIMIT 0"))
    _ready = True
    Path("/tmp/tutorbot-worker-heartbeat").touch()


@heartbeat_sent.connect  # type: ignore[misc]
def mark_heartbeat(**kwargs: Any) -> None:
    if _ready:
        Path("/tmp/tutorbot-worker-heartbeat").touch()
