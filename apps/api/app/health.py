from collections.abc import Callable
from typing import Literal

import httpx
import psycopg
from pydantic import BaseModel
from redis import Redis

from app.config import Settings


class HealthReport(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, Literal["ok", "unavailable"]]


def check_database(settings: Settings) -> None:
    with psycopg.connect(settings.database_url.get_secret_value(), connect_timeout=3) as connection:
        row = connection.execute(
            "SELECT extversion FROM pg_extension WHERE extname = 'vector'"
        ).fetchone()
        if row is None:
            raise RuntimeError("vector extension missing")
        role = connection.execute(
            "SELECT rolname,rolsuper,rolcreatedb,rolcreaterole,rolbypassrls "
            "FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        if role != (f"tutorbot_{settings.service_mode}", False, False, False, False):
            raise RuntimeError("unsafe service database role")


def check_redis(settings: Settings) -> None:
    with Redis.from_url(settings.redis_url, socket_timeout=3, socket_connect_timeout=3) as client:
        client.ping()


def check_http(url: str) -> None:
    with httpx.Client(timeout=3) as client:
        client.get(url).raise_for_status()


def readiness(settings: Settings) -> HealthReport:
    proxy_origin = settings.litellm_base_url.removesuffix("/v1")
    probes: dict[str, Callable[[], None]] = {
        "database": lambda: check_database(settings),
        "redis": lambda: check_redis(settings),
        "storage": lambda: check_http(f"{settings.storage_emulator_host}/storage/v1/b"),
        "auth": lambda: check_http(f"http://{settings.firebase_auth_emulator_host}/"),
        "model_proxy": lambda: check_http(f"{proxy_origin}/health/liveliness"),
    }
    if settings.service_mode == "admin":
        probes = {name: probes[name] for name in ("database", "auth")}
    checks: dict[str, Literal["ok", "unavailable"]] = {}
    for name, probe in probes.items():
        try:
            probe()
            checks[name] = "ok"
        except Exception:
            # Return service names only: exceptions can contain credentials or content.
            checks[name] = "unavailable"
    return HealthReport(
        status="ok" if all(v == "ok" for v in checks.values()) else "unavailable", checks=checks
    )
