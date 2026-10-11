from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.audit import AuditEvent
from app.auth.identity import Identity, Principal, require_admin, require_student
from app.db import database_session
from app.students.repository import StudentAccounts

router = APIRouter(prefix="/v1")
student = APIRouter(prefix="/student", dependencies=[Depends(require_student)])
admin = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
StudentIdentity = Annotated[Principal, Depends(require_student)]
DBSession = Annotated[Session, Depends(database_session)]


class IdentityResponse(BaseModel):
    role: Literal["student", "admin"]


class AccountResponse(BaseModel):
    id: UUID


@router.get("/auth/me", response_model=IdentityResponse)
def me(principal: Identity) -> IdentityResponse:
    return IdentityResponse(role=principal.role)


@student.get("/account", response_model=AccountResponse)
def own_account(principal: StudentIdentity, session: DBSession) -> AccountResponse:
    return AccountResponse(id=StudentAccounts(session, principal).own_account().id)


@student.get("/accounts/{account_id}", response_model=AccountResponse)
def account_by_id(
    account_id: UUID, principal: StudentIdentity, session: DBSession
) -> AccountResponse:
    account = StudentAccounts(session, principal).get_owned(account_id)
    if account is None:
        raise HTTPException(404, "Account not found")
    return AccountResponse(id=account.id)


@admin.get("/access", response_model=IdentityResponse)
def admin_access(principal: Annotated[Principal, Depends(require_admin)]) -> IdentityResponse:
    return IdentityResponse(role=principal.role)


class AuditResponse(BaseModel):
    id: UUID
    actor_role: str | None
    target: str
    status_code: int
    outcome: str
    created_at: datetime


@admin.get("/audit", response_model=list[AuditResponse])
def recent_audit(
    principal: Annotated[Principal, Depends(require_admin)], session: DBSession
) -> list[AuditResponse]:
    events = session.scalars(
        select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(100)
    ).all()
    return [
        AuditResponse(
            id=e.id,
            actor_role=e.actor_role,
            target=e.target,
            status_code=e.status_code,
            outcome=e.outcome,
            created_at=e.created_at,
        )
        for e in events
    ]
