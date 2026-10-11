"""Privileged synthetic-account fixture setup. Never runs against production."""

from firebase_admin import auth

from app.auth.identity import firebase_app
from app.config import Settings

settings = Settings()
if (
    settings.app_env != "local"
    or not settings.firebase_auth_emulator_host
    or settings.google_cloud_project != "demo-tutorbot"
):
    raise RuntimeError("Synthetic accounts require the local demo-tutorbot emulator")

app = firebase_app()
for uid, email, role in [
    ("demo-student-a", "student-a@example.test", "student"),
    ("demo-student-b", "student-b@example.test", "student"),
    ("demo-maintainer", "maintainer@example.test", "admin"),
]:
    try:
        auth.get_user(uid, app=app)
    except auth.UserNotFoundError:
        auth.create_user(uid=uid, email=email, password="TutorBot-local-123!", app=app)
    auth.set_custom_user_claims(uid, {"role": role}, app=app)
print("Synthetic local accounts ready (two students and one maintainer).")
