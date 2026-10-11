from typing import Literal

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")
    database_url: SecretStr = SecretStr(
        "postgresql://tutorbot_runtime:unconfigured@db:5432/tutorbot"
    )
    service_mode: Literal["runtime", "admin"] = "runtime"
    redis_url: str = "redis://redis:6379/0"
    storage_emulator_host: str | None = None
    student_private_bucket: str = "student-private"
    curriculum_published_bucket: str = "curriculum-published"
    teaching_private_bucket: str = "teaching-private"
    object_retention_days: int = 30
    app_env: Literal["local", "test", "production"] = "production"
    google_cloud_project: str = "demo-tutorbot"
    firebase_auth_emulator_host: str | None = None
    litellm_base_url: str = "http://litellm:4000/v1"
    litellm_master_key: SecretStr = SecretStr("not-configured")

    @model_validator(mode="after")
    def safe_auth_mode(self) -> "Settings":
        if self.firebase_auth_emulator_host:
            if self.app_env == "production" or not self.google_cloud_project.startswith("demo-"):
                raise ValueError("Auth emulator requires local/test mode and a demo project")
        if self.storage_emulator_host and self.app_env == "production":
            raise ValueError("Storage emulator requires local/test mode")
        if not 1 <= self.object_retention_days <= 3650:
            raise ValueError("Invalid object retention period")
        return self


def require_service_credentials(settings: Settings) -> None:
    from sqlalchemy.engine import make_url

    if (
        make_url(settings.database_url.get_secret_value()).username
        != f"tutorbot_{settings.service_mode}"
    ):
        raise ValueError("API must use its own restricted database role")
