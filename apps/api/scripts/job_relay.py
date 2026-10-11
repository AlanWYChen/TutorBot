"""Durable outbox relay. Never logs payloads, student IDs or exception messages."""

import logging
import time
from pathlib import Path

from app.config import Settings
from app.db import engine
from app.private_io.celery_app import CeleryPublisher
from app.private_io.runner import relay, require_worker_credentials

settings = Settings()
require_worker_credentials(settings)
while True:
    try:
        relay(engine(), settings, CeleryPublisher())
        Path("/tmp/tutorbot-relay-heartbeat").touch()
    except Exception:
        logging.warning("job_relay_unavailable")
    time.sleep(2)
