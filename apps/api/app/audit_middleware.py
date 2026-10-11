from typing import cast
from uuid import uuid4

from fastapi import Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.audit import ROUTES, AuditEvent, Route, SafeEvent, log_event
from app.auth.identity import Principal
from app.config import Settings
from app.db import engine


def save_audit(event: SafeEvent, principal: Principal | None, method: str) -> None:
    with Session(engine()) as session, session.begin():
        session.add(
            AuditEvent(
                id=event.request_id,
                actor_uid=principal.uid if principal else None,
                actor_role=principal.role if principal else None,
                action=event.action,
                target=event.route,
                method=method
                if method in {"GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS", "HEAD"}
                else "OTHER",
                status_code=event.status_code,
                outcome=event.outcome,
            )
        )


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        if not request.url.path.startswith("/v1/"):
            return await call_next(request)
        request_id = uuid4()
        try:
            response = await call_next(request)
        except Exception:
            response = JSONResponse({"detail": "Service unavailable"}, status_code=503)
        # Resolve only known templates; never retain raw path IDs/query strings.
        registered = request.url.path
        if registered.startswith("/v1/student/accounts/") and registered.count("/") == 4:
            registered = "/v1/student/accounts/{account_id}"
        route = cast(Route, registered if registered in ROUTES else "unmatched")
        code = response.status_code
        event = SafeEvent(
            request_id=request_id,
            service=Settings().service_mode,
            action="http_request",
            route=route,
            status_code=code,
            outcome="success" if code < 400 else "denied" if code < 500 else "error",
        )
        principal = getattr(request.state, "principal", None)
        try:
            # Synchronous DB work runs outside the async event loop.
            from starlette.concurrency import run_in_threadpool

            await run_in_threadpool(save_audit, event, principal, request.method)
        except Exception:
            log_event(
                event.model_copy(
                    update={"action": "audit_unavailable", "status_code": 503, "outcome": "error"}
                )
            )
            if code < 400:
                event = event.model_copy(update={"status_code": 503, "outcome": "error"})
                response = JSONResponse({"detail": "Service unavailable"}, status_code=503)
        log_event(event)
        response.headers["X-Request-ID"] = str(request_id)
        response.headers["Cache-Control"] = "no-store"
        return response
