"""Real PostgreSQL + Firebase emulator integration; run via make auth-integration."""

import base64
import json
import os
import time
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from firebase_admin import auth
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.identity import firebase_app
from app.config import Settings
from app.db import engine
from app.main import app
from app.students.models import StudentAccount, User

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_AUTH_INTEGRATION") != "1", reason="Requires local DB and Firebase emulator"
)


def login(email: str) -> str:
    settings = Settings()
    response = httpx.post(
        f"http://{settings.firebase_auth_emulator_host}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=demo-key",
        json={"email": email, "password": "TutorBot-local-123!", "returnSecureToken": True},
    )
    response.raise_for_status()
    return str(response.json()["idToken"])


def alter_token(token: str, updates: dict[str, object]) -> str:
    head, body, signature = token.split(".")
    claims = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    claims.update(updates)
    return (
        head
        + "."
        + base64.urlsafe_b64encode(json.dumps(claims).encode()).decode().rstrip("=")
        + "."
        + signature
    )


def test_real_auth_rbac_and_tenant_scope() -> None:
    client = TestClient(app)
    admin_client = httpx.Client(base_url="http://admin-api:8000", timeout=10)
    a_token, b_token, admin_token = [
        login(e)
        for e in ["student-a@example.test", "student-b@example.test", "maintainer@example.test"]
    ]
    a, b, admin = [
        {"Authorization": f"Bearer {token}"} for token in [a_token, b_token, admin_token]
    ]
    a_id = client.get("/v1/student/account", headers=a).json()["id"]
    b_id = client.get("/v1/student/account", headers=b).json()["id"]
    assert a_id != b_id
    assert client.get(f"/v1/student/accounts/{a_id}", headers=a).status_code == 200
    assert client.get(f"/v1/student/accounts/{a_id}", headers=b).status_code == 404
    assert client.get(f"/v1/student/accounts/{b_id}", headers=a).status_code == 404
    assert client.get(f"/v1/student/accounts/{uuid4()}", headers=b).status_code == 404
    assert (
        client.get(
            "/v1/student/account",
            headers={**b, "X-Student-ID": a_id, "X-Role": "admin"},
            params={"student_id": a_id, "role": "admin"},
        ).json()["id"]
        == b_id
    )
    assert admin_client.get("/v1/admin/access", headers=a).status_code == 403
    assert admin_client.get("/v1/admin/access", headers=b).status_code == 403
    assert admin_client.get("/v1/admin/access", headers=admin).status_code == 200
    assert client.get("/v1/student/account", headers=admin).status_code == 403
    assert client.get("/v1/student/account", headers=a).json()["id"] == a_id
    with Session(engine()) as session:
        assert (
            session.scalar(
                select(func.count())
                .select_from(StudentAccount)
                .join(User)
                .where(User.firebase_uid.in_(["demo-student-a", "demo-student-b"]))
            )
            == 2
        )
    for bad in [
        "broken",
        alter_token(a_token, {"exp": int(time.time()) - 120}),
        alter_token(a_token, {"aud": "wrong-project"}),
        alter_token(a_token, {"iss": "https://evil.invalid"}),
        alter_token(a_token, {"role": "admin"}),
    ]:
        assert (
            client.get("/v1/auth/me", headers={"Authorization": f"Bearer {bad}"}).status_code == 401
        )


def test_disabled_user_and_removed_admin_role_denied() -> None:
    client = TestClient(app)
    admin_client = httpx.Client(base_url="http://admin-api:8000", timeout=10)
    token = login("student-b@example.test")
    auth.update_user("demo-student-b", disabled=True, app=firebase_app())
    try:
        assert (
            client.get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
            == 401
        )
    finally:
        auth.update_user("demo-student-b", disabled=False, app=firebase_app())
    token = login("maintainer@example.test")
    auth.set_custom_user_claims("demo-maintainer", {"role": "student"}, app=firebase_app())
    try:
        assert (
            admin_client.get(
                "/v1/admin/access", headers={"Authorization": f"Bearer {token}"}
            ).status_code
            == 401
        )
    finally:
        auth.set_custom_user_claims("demo-maintainer", {"role": "admin"}, app=firebase_app())


def test_revoked_token_denied() -> None:
    token = login("student-b@example.test")
    time.sleep(1.1)  # Firebase auth_time is second-granularity.
    auth.revoke_refresh_tokens("demo-student-b", app=firebase_app())
    assert (
        TestClient(app).get("/v1/auth/me", headers={"Authorization": f"Bearer {token}"}).status_code
        == 401
    )
