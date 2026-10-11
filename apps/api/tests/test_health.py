from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import Settings
from app.health import HealthReport, readiness
from app.main import app

client = TestClient(app)


def test_live_does_not_depend_on_external_services() -> None:
    assert client.get("/health/live").json() == {"status": "ok", "service": "api"}


def test_readiness_returns_503_without_leaking_secrets() -> None:
    with patch(
        "app.main.readiness",
        return_value=HealthReport(status="unavailable", checks={"database": "unavailable"}),
    ):
        response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable", "checks": {"database": "unavailable"}}


def test_dependencies_and_exception_redaction() -> None:
    with (
        patch("app.health.check_database", side_effect=RuntimeError("password=secret")),
        patch("app.health.check_redis"),
        patch("app.health.check_http"),
    ):
        report = readiness(Settings())
    assert report.status == "unavailable"
    assert report.checks["database"] == "unavailable"
    assert len(report.checks) == 5
    assert "secret" not in report.model_dump_json()


def test_admin_readiness_needs_only_its_dependencies() -> None:
    with (
        patch("app.health.check_database"),
        patch("app.health.check_http") as http,
        patch("app.health.check_redis") as redis,
    ):
        report = readiness(Settings(service_mode="admin"))
    assert report.status == "ok"
    assert set(report.checks) == {"database", "auth"}
    assert http.call_count == 1
    redis.assert_not_called()
