from time import time
from unittest.mock import Mock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.auth.identity import verify_token
from app.config import Settings
from app.main import app


@pytest.mark.parametrize("path", ["/v1/auth/me", "/v1/student/account"])
def test_missing_token_denied(path: str) -> None:
    assert TestClient(app).get(path).status_code == 401


def test_uses_verified_identity_and_revocation_check() -> None:
    with (
        patch("app.auth.identity.firebase_app", return_value="app"),
        patch(
            "app.auth.identity.auth.verify_id_token",
            return_value={
                "uid": "a",
                "role": "student",
                "exp": int(time()) + 3600,
                "iat": int(time()),
                "auth_time": int(time()),
            },
        ) as verify,
        patch(
            "app.auth.identity.auth.get_user", return_value=Mock(custom_claims={"role": "student"})
        ),
    ):
        assert verify_token("token").uid == "a"
        verify.assert_called_once_with("token", app="app", check_revoked=True)


@pytest.mark.parametrize(
    "claims,current_role", [({"uid": "a", "role": "admin"}, "student"), ({"uid": "a"}, "unknown")]
)
def test_stale_or_unknown_role_denied(claims: dict[str, str], current_role: str) -> None:
    with (
        patch("app.auth.identity.firebase_app"),
        patch(
            "app.auth.identity.auth.verify_id_token",
            return_value={
                **claims,
                "exp": int(time()) + 3600,
                "iat": int(time()),
                "auth_time": int(time()),
            },
        ),
        patch(
            "app.auth.identity.auth.get_user",
            return_value=Mock(custom_claims={"role": current_role}),
        ),
    ):
        with pytest.raises(HTTPException) as error:
            verify_token("token")
    assert error.value.status_code == 401


@pytest.mark.parametrize(
    "mode,project", [("production", "demo-tutorbot"), ("local", "live-project")]
)
def test_unsafe_emulator_configuration_fails(mode: str, project: str) -> None:
    with pytest.raises(ValidationError):
        Settings(
            app_env=mode, google_cloud_project=project, firebase_auth_emulator_host="firebase:9099"
        )  # type: ignore[arg-type]


def test_runtime_does_not_mount_admin_routes() -> None:
    assert TestClient(app).get("/v1/admin/access").status_code == 404
