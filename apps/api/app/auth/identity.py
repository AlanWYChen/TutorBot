from functools import lru_cache
from time import time
from typing import Annotated, Literal

import firebase_admin  # type: ignore[import-untyped]
from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from firebase_admin import auth
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from app.config import Settings


class Principal(BaseModel):
    model_config = ConfigDict(frozen=True)
    uid: str
    role: Literal["student", "admin"]


class TokenClaims(BaseModel):
    uid: str = Field(min_length=1, max_length=128)
    role: Literal["student", "admin"] = "student"
    exp: StrictInt
    iat: StrictInt
    auth_time: StrictInt


@lru_cache
def firebase_app() -> firebase_admin.App:
    settings = Settings()
    return firebase_admin.initialize_app(options={"projectId": settings.google_cloud_project})


def verify_token(token: str) -> Principal:
    try:
        app = firebase_app()
        claims = TokenClaims.model_validate(
            auth.verify_id_token(token, app=app, check_revoked=True)
        )
        now = time()
        # Firebase's emulator omits time checks; enforce the same contract in every mode.
        if (
            claims.exp <= now
            or claims.iat > now
            or claims.auth_time > claims.iat
            or claims.exp <= claims.iat
        ):
            raise ValueError("invalid token timestamps")
        # Consult privileged current claims; stale role-bearing tokens fail closed.
        user = auth.get_user(claims.uid, app=app)
        role = (user.custom_claims or {}).get("role", "student")
        if role not in ("student", "admin") or claims.role != role:
            raise ValueError("invalid or stale role")
        return Principal(uid=claims.uid, role=role)
    except Exception:
        raise HTTPException(
            401, "Invalid or expired sign-in", headers={"WWW-Authenticate": "Bearer"}
        ) from None


bearer = HTTPBearer(auto_error=False)


def current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)],
    request: Request,
) -> Principal:
    if credentials is None:
        raise HTTPException(401, "Sign-in required", headers={"WWW-Authenticate": "Bearer"})
    principal = verify_token(credentials.credentials)
    request.state.principal = principal
    return principal


Identity = Annotated[Principal, Depends(current_principal)]


def require_student(principal: Identity) -> Principal:
    if principal.role != "student":
        raise HTTPException(403, "Student access required")
    return principal


def require_admin(principal: Identity) -> Principal:
    if principal.role != "admin":
        raise HTTPException(403, "Maintainer access required")
    return principal
