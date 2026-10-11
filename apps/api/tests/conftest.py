import os

import pytest


@pytest.fixture(autouse=True)
def isolate_unit_audit(monkeypatch: pytest.MonkeyPatch) -> None:
    if os.environ.get("RUN_AUTH_INTEGRATION") != "1":
        monkeypatch.setattr("app.audit_middleware.save_audit", lambda *args: None)
