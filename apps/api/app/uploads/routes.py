import asyncio
import time
from typing import Annotated, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import ValidationError
from python_multipart.exceptions import MultipartParseError
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.formparsers import MultiPartException
from starlette.responses import Response
from starlette.types import Message

from app.auth.identity import Principal, require_admin, require_student
from app.domain.contracts import (
    AssessmentStatus,
    AssessmentUpload,
    JobAccepted,
    KnowledgeUpload,
    KnowledgeUploadStatus,
)
from app.limits import MAX_MULTIPART_BYTES, MAX_UPLOAD_BYTES
from app.private_io.types import StorageError
from app.uploads.service import read_upload, save_upload, upload_status
from app.uploads.validation import UploadRejected, validate_pdf

student_uploads = APIRouter(prefix="/v1/student/assessments")
admin_uploads = APIRouter(prefix="/v1/admin/knowledge")
Student = Annotated[Principal, Depends(require_student)]
Admin = Annotated[Principal, Depends(require_admin)]
_slots = asyncio.Semaphore(2)


async def receive_upload(request: Request, principal: Principal, key: str | None) -> JobAccepted:
    try:
        idempotency = UUID(key or "")
    except ValueError:
        raise HTTPException(422, "A UUID Idempotency-Key is required") from None
    if request.headers.get("content-encoding", "identity").lower() != "identity":
        raise HTTPException(415, "Compressed upload bodies are not supported")
    if request.headers.get("content-type", "").split(";", 1)[0].lower() != "multipart/form-data":
        raise HTTPException(415, "A multipart PDF upload is required")
    lengths = request.headers.getlist("content-length")
    if lengths:
        try:
            if len(lengths) != 1 or int(lengths[0]) < 0:
                raise ValueError
            if int(lengths[0]) > MAX_MULTIPART_BYTES:
                raise HTTPException(413, "Upload exceeds the size limit")
        except ValueError:
            raise HTTPException(400, "Invalid upload length") from None
    consumed = 0
    deadline = time.monotonic() + 60

    async def bounded_receive() -> Message:
        nonlocal consumed
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise MultiPartException("upload_timeout")
        try:
            message = await asyncio.wait_for(request.receive(), timeout=min(10, remaining))
        except TimeoutError:
            raise MultiPartException("upload_timeout") from None
        if message["type"] == "http.disconnect":
            raise MultiPartException("upload_interrupted")
        if message["type"] == "http.request":
            consumed += len(message.get("body", b""))
            if consumed > MAX_MULTIPART_BYTES:
                # Multipart parser closes all partial files on this exception type.
                raise MultiPartException("upload_body_limit")
        return message

    try:
        await asyncio.wait_for(_slots.acquire(), timeout=0.1)
    except TimeoutError:
        raise HTTPException(429, "Upload capacity is busy; retry shortly") from None
    try:
        bounded = Request(request.scope, receive=bounded_receive)
        async with bounded.form(max_files=1, max_fields=1, max_part_size=16 * 1024) as form:
            if set(form.keys()) != {"file", "metadata"} or len(form.multi_items()) != 2:
                raise UploadRejected("invalid_upload_fields", 400)
            file, metadata_json = form["file"], form["metadata"]
            if not isinstance(file, UploadFile) or not isinstance(metadata_json, str):
                raise UploadRejected("invalid_upload_fields", 400)
            contract = AssessmentUpload if principal.role == "student" else KnowledgeUpload
            try:
                metadata = contract.model_validate_json(metadata_json)
            except ValidationError:
                raise UploadRejected("invalid_upload_metadata") from None
            data = await file.read(MAX_UPLOAD_BYTES + 1)
            await run_in_threadpool(
                validate_pdf, data, metadata, file.filename or "", file.content_type or ""
            )
            return await run_in_threadpool(save_upload, principal, metadata, data, idempotency)
    except UploadRejected as exc:
        raise HTTPException(exc.status, exc.code) from None
    except StarletteHTTPException as exc:
        if exc.detail == "upload_timeout":
            raise HTTPException(408, "Upload timed out") from None
        if exc.detail == "upload_body_limit":
            raise HTTPException(413, "Upload exceeds the size limit") from None
        raise HTTPException(exc.status_code, "Invalid upload") from None
    except (MultiPartException, MultipartParseError):
        raise HTTPException(400, "Invalid upload") from None
    except StorageError:
        raise HTTPException(503, "Private storage is unavailable") from None
    except Exception:
        raise HTTPException(503, "Upload is unavailable; retry with the same key") from None
    finally:
        _slots.release()


UPLOAD_OPENAPI = {
    "parameters": [
        {
            "name": "Idempotency-Key",
            "in": "header",
            "required": True,
            "schema": {"type": "string", "format": "uuid"},
        }
    ],
    "requestBody": {
        "required": True,
        "content": {
            "multipart/form-data": {
                "schema": {
                    "type": "object",
                    "required": ["file", "metadata"],
                    "additionalProperties": False,
                    "properties": {
                        "file": {"type": "string", "format": "binary"},
                        "metadata": {
                            "type": "string",
                            "description": "JSON AssessmentUpload or KnowledgeUpload metadata. "
                            "PDF only, up to 25 MB and 200 pages.",
                        },
                    },
                }
            }
        },
    },
}


@student_uploads.post(
    "/upload", response_model=JobAccepted, status_code=202, openapi_extra=UPLOAD_OPENAPI
)
async def student_upload(request: Request, principal: Student) -> JobAccepted:
    return await receive_upload(request, principal, request.headers.get("idempotency-key"))


@admin_uploads.post(
    "/upload", response_model=JobAccepted, status_code=202, openapi_extra=UPLOAD_OPENAPI
)
async def admin_upload(request: Request, principal: Admin) -> JobAccepted:
    return await receive_upload(request, principal, request.headers.get("idempotency-key"))


def private_file(principal: Principal, resource_id: UUID) -> Response:
    try:
        data = read_upload(principal, resource_id)
    except LookupError:
        raise HTTPException(404, "Document not found") from None
    except StorageError:
        raise HTTPException(503, "Private storage is unavailable") from None
    return Response(
        data,
        media_type="application/pdf",
        headers={
            "Content-Disposition": 'attachment; filename="document.pdf"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@student_uploads.get(
    "/{resource_id}/file",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def student_file(resource_id: UUID, principal: Student) -> Response:
    return private_file(principal, resource_id)


@admin_uploads.get(
    "/{resource_id}/file",
    response_class=Response,
    responses={
        200: {"content": {"application/pdf": {"schema": {"type": "string", "format": "binary"}}}}
    },
)
def admin_file(resource_id: UUID, principal: Admin) -> Response:
    return private_file(principal, resource_id)


def private_status(
    principal: Principal, resource_id: UUID
) -> AssessmentStatus | KnowledgeUploadStatus:
    try:
        return upload_status(principal, resource_id)
    except LookupError:
        raise HTTPException(404, "Document not found") from None


@student_uploads.get("/{resource_id}/status", response_model=AssessmentStatus)
def student_status(resource_id: UUID, principal: Student) -> AssessmentStatus:
    return cast(AssessmentStatus, private_status(principal, resource_id))


@admin_uploads.get("/{resource_id}/status", response_model=KnowledgeUploadStatus)
def admin_status(resource_id: UUID, principal: Admin) -> KnowledgeUploadStatus:
    return cast(KnowledgeUploadStatus, private_status(principal, resource_id))
