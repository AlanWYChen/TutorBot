"""Cloud Run Job entry point; image's IAM identity supplies DB/GCS credentials."""

import os
from uuid import UUID

from app.config import Settings
from app.db import engine
from app.private_io.runner import require_worker_credentials, run_job

settings = Settings()
require_worker_credentials(settings)
run_job(engine(), settings, UUID(os.environ["TUTORBOT_JOB_ID"]))
