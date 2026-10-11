import json
from unittest.mock import patch
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.audit import SafeEvent, log_event
from app.auth.identity import Principal
from app.main import app


def test_logging_rejects_unbounded_content() -> None:
    event = dict(
        request_id=uuid4(),
        service="runtime",
        action="http_request",
        route="unmatched",
        status_code=401,
        outcome="denied",
    )
    for extra in [
        {"token": "secret"},
        {"route": "/student/private-answer"},
        {"exception": "password=secret"},
    ]:
        with pytest.raises(ValidationError):
            SafeEvent.model_validate({**event, **extra})
    with patch("app.audit.logging.getLogger") as logger:
        log_event(SafeEvent.model_validate(event))
        output = logger.return_value.info.call_args.args[0]
    assert set(json.loads(output)) == set(event)
    assert "secret" not in output


def test_unknown_route_and_auth_denial_do_not_log_request_content() -> None:
    with (
        patch("app.audit_middleware.log_event") as logs,
        patch("app.audit_middleware.save_audit") as save,
    ):
        response = TestClient(app).get(
            "/v1/secret-student-answer?token=secret",
            headers={"X-Request-ID": "secret", "Authorization": "Bearer secret"},
        )
    assert response.status_code == 404
    event = logs.call_args.args[0]
    assert event.route == "unmatched"
    assert "secret" not in event.model_dump_json()
    assert response.headers["X-Request-ID"] != "secret"
    assert save.call_args.args[1] is None


def test_audit_failure_closes_successful_response_without_leaking_error() -> None:
    with (
        patch(
            "app.auth.identity.verify_token",
            return_value=Principal(uid="synthetic", role="student"),
        ),
        patch(
            "app.audit_middleware.save_audit",
            side_effect=RuntimeError("private answer password=secret"),
        ),
        patch("app.audit_middleware.log_event") as logs,
    ):
        response = TestClient(app).get("/v1/auth/me", headers={"Authorization": "Bearer token"})
    assert response.status_code == 503
    assert response.json() == {"detail": "Service unavailable"}
    assert all("secret" not in call.args[0].model_dump_json() for call in logs.call_args_list)
    assert logs.call_args.args[0].status_code == 503


def test_service_refuses_owner_credentials() -> None:
    from app.config import Settings, require_service_credentials

    for role in ["tutorbot", "tutorbot_migrator", "tutorbot_admin"]:
        with pytest.raises(ValueError, match="restricted"):
            require_service_credentials(
                Settings(database_url=f"postgresql://{role}:synthetic@db/tutorbot")
            )
