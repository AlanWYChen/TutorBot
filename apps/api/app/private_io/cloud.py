"""Cloud publisher contracts. Deployment supplies an ADC-authenticated HTTP client.

No public worker endpoint or cloud resources are created by this foundation step.
The receiver must verify Cloud Tasks OIDC/IAM before calling the shared DB runner.
"""

import re
from typing import Protocol
from urllib.parse import urlsplit
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class AuthorizedCloudHTTP(Protocol):
    def post_json(self, url: str, body: dict[str, object]) -> None: ...


class CloudTasksTarget(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    project: str = Field(pattern=r"^[a-z][a-z0-9-]{4,61}[a-z0-9]$")
    location: str = Field(pattern=r"^[a-z0-9-]+$")
    queue: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    worker_url: str
    audience: str
    service_account_email: str

    @model_validator(mode="after")
    def validate_target(self) -> "CloudTasksTarget":
        for url in (self.worker_url, self.audience):
            parsed = urlsplit(url)
            if (
                parsed.scheme != "https"
                or not parsed.hostname
                or parsed.username
                or parsed.password
                or parsed.query
                or parsed.fragment
            ):
                raise ValueError("Cloud worker requires a fixed HTTPS target")
        if not re.fullmatch(
            r"[a-zA-Z0-9_-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com", self.service_account_email
        ):
            raise ValueError("Cloud task requires a dedicated service account")
        return self

    @property
    def parent(self) -> str:
        return f"projects/{self.project}/locations/{self.location}/queues/{self.queue}"


class CloudTasksPublisher:
    def __init__(self, target: CloudTasksTarget, transport: AuthorizedCloudHTTP):
        self.target, self.transport = target, transport

    def publish(self, job_id: UUID) -> None:
        import base64
        import json

        url = f"https://cloudtasks.googleapis.com/v2/{self.target.parent}/tasks"
        self.transport.post_json(
            url,
            {
                # Do not use permanent job ID as task name: an expired DB lease may
                # need a new delivery during Cloud Tasks' task-name deduplication window.
                "task": {
                    "httpRequest": {
                        "httpMethod": "POST",
                        "url": self.target.worker_url,
                        "headers": {"Content-Type": "application/json"},
                        "body": base64.b64encode(
                            json.dumps({"job_id": str(job_id)}).encode()
                        ).decode(),
                        "oidcToken": {
                            "serviceAccountEmail": self.target.service_account_email,
                            "audience": self.target.audience,
                        },
                    },
                    "dispatchDeadline": "90s",
                },
            },
        )


class CloudRunJobsPublisher:
    """Bounded run-job request; job definition fixes image, identity and command."""

    def __init__(self, resource: str, transport: AuthorizedCloudHTTP):
        if not re.fullmatch(r"projects/[a-z0-9-]+/locations/[a-z0-9-]+/jobs/[a-z0-9-]+", resource):
            raise ValueError("Invalid configured Cloud Run Job")
        self.resource, self.transport = resource, transport

    def publish(self, job_id: UUID) -> None:
        self.transport.post_json(
            f"https://run.googleapis.com/v2/{self.resource}:run",
            {
                "overrides": {
                    "taskCount": 1,
                    "timeout": "90s",
                    "containerOverrides": [
                        {"env": [{"name": "TUTORBOT_JOB_ID", "value": str(job_id)}]}
                    ],
                },
            },
        )
