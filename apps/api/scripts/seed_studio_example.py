"""Local-only synthetic studio fixture; no student accounts/documents are read."""

import hashlib
import json
from uuid import NAMESPACE_URL, uuid5

import httpx
import pymupdf

from app.config import Settings

settings = Settings()
if settings.app_env != "local" or not settings.firebase_auth_emulator_host:
    raise RuntimeError("Synthetic studio fixture requires local emulators")
with pymupdf.open() as doc:
    for number in (1, 2):
        page = doc.new_page()
        page.insert_text((72, 50), "Synthetic teaching example - no student data")
        page.insert_text((72, 90), f"{number}. Solve x^2 - 4 = 0.")
        page.insert_text((72, 120), "Response: x = 2")
        page.insert_text(
            (72, 150), "Teacher mark: 1/2. The negative root is missing.", color=(1, 0, 0)
        )
    data = doc.tobytes()
response = httpx.post(
    f"http://{settings.firebase_auth_emulator_host}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=demo-key",
    json={
        "email": "maintainer@example.test",
        "password": "TutorBot-local-123!",
        "returnSecureToken": True,
    },
)
response.raise_for_status()
metadata = {
    "filename": "synthetic-marked-quadratics.pdf",
    "media_type": "application/pdf",
    "size_bytes": len(data),
    "sha256": hashlib.sha256(data).hexdigest(),
    "title": "Synthetic marked quadratics",
    "author": "TutorBot synthetic fixture",
    "publisher": "Local development",
    "kind": "reference",
    "source_authority": "supplemental",
    "license_metadata": {"rights": "Generated synthetic source; fixture only"},
}
with httpx.Client(base_url="http://web:3000", timeout=60) as web:
    response = web.post(
        "/api/studio/upload",
        headers={
            "Authorization": "Bearer " + response.json()["idToken"],
            "Idempotency-Key": str(uuid5(NAMESPACE_URL, "tutorbot/p102/example/v1")),
        },
        files={
            "file": (metadata["filename"], data, "application/pdf"),
            "metadata": (None, json.dumps(metadata)),
        },
    )
    # PDF serialization has fresh document IDs; use a new fixture when replay conflicts.
    if response.status_code == 409:
        from uuid import uuid4

        token = httpx.post(
            f"http://{settings.firebase_auth_emulator_host}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=demo-key",
            json={
                "email": "maintainer@example.test",
                "password": "TutorBot-local-123!",
                "returnSecureToken": True,
            },
        ).json()["idToken"]
        response = web.post(
            "/api/studio/upload",
            headers={"Authorization": "Bearer " + token, "Idempotency-Key": str(uuid4())},
            files={
                "file": (metadata["filename"], data, "application/pdf"),
                "metadata": (None, json.dumps(metadata)),
            },
        )
    response.raise_for_status()
print("Synthetic maintainer source is available for local review.")
