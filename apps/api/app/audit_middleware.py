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
        segments = registered.split("/")
        if (
            len(segments) == 6
            and segments[1] == "v1"
            and tuple(segments[2:4]) in {("student", "assessments"), ("admin", "knowledge")}
            and segments[5] in {"file", "status"}
        ):
            registered = "/".join([*segments[:4], "{resource_id}", segments[5]])
        if (
            len(segments) == 6
            and segments[1:4] == ["v1", "student", "assessments"]
            and segments[5] in {"render", "pages"}
        ):
            registered = "/".join([*segments[:4], "{assessment_id}", segments[5]])
        if (
            len(segments) == 8
            and segments[1:4] == ["v1", "student", "assessments"]
            and segments[5] == "pages"
            and segments[7] == "image"
        ):
            registered = "/v1/student/assessments/{assessment_id}/pages/{page_number}/image"
        if segments[1:5] == ["v1", "admin", "studio", "sources"]:
            if len(segments) == 6:
                registered = "/v1/admin/studio/sources/{document_id}"
            elif len(segments) == 7 and segments[6] == "restore":
                registered = "/v1/admin/studio/sources/{document_id}/restore"
            elif len(segments) == 8 and segments[6] == "pages":
                registered = "/v1/admin/studio/sources/{document_id}/pages/{number}"
            elif len(segments) == 9 and segments[6] == "pages" and segments[8] == "restore":
                registered = "/v1/admin/studio/sources/{document_id}/pages/{number}/restore"
            elif len(segments) == 9 and segments[6] == "annotations" and segments[8] == "restore":
                registered = (
                    "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}/restore"
                )
            if len(segments) == 7 and segments[6] in {"render", "pages", "annotations"}:
                registered = f"/v1/admin/studio/sources/{{document_id}}/{segments[6]}"
            elif len(segments) == 9 and segments[6] == "pages" and segments[8] == "image":
                registered = "/v1/admin/studio/sources/{document_id}/pages/{number}/image"
            elif len(segments) == 8 and segments[6] == "annotations":
                registered = "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}"
            elif len(segments) == 9 and segments[6] == "annotations" and segments[8] == "crop":
                registered = (
                    "/v1/admin/studio/sources/{document_id}/annotations/{annotation_id}/crop"
                )
        if segments[1:5] == ["v1", "admin", "studio", "datasets"]:
            if len(segments) == 7 and segments[6] in {"cases", "export", "import"}:
                registered = f"/v1/admin/studio/datasets/{{dataset_id}}/{segments[6]}"
            elif (
                len(segments) == 9
                and segments[6] == "cases"
                and segments[8] in {"review", "crop", "annotation"}
            ):
                registered = (
                    f"/v1/admin/studio/datasets/{{dataset_id}}/cases/{{case_id}}/{segments[8]}"
                )
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
