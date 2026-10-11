"""Local emulator bucket provisioning only; cloud buckets are provisioned via IaC."""

from google.api_core.exceptions import Conflict
from google.auth.credentials import AnonymousCredentials
from google.cloud import storage

from app.config import Settings

settings = Settings()
if settings.app_env != "local" or not settings.storage_emulator_host:
    raise RuntimeError("Storage bootstrap is local emulator only")
client = storage.Client(
    project=settings.google_cloud_project,
    credentials=AnonymousCredentials(),
    client_options={"api_endpoint": settings.storage_emulator_host},
)
for name in (
    settings.student_private_bucket,
    settings.curriculum_published_bucket,
    settings.teaching_private_bucket,
):
    try:
        client.create_bucket(name)
    except Conflict:
        pass
print("Local private storage buckets configured.")
