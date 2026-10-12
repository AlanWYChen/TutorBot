import asyncio
from typing import Annotated, TypeVar
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path, Request
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from app.assessments.types import AssessmentListItem, PageView
from app.auth.identity import Principal, require_admin
from app.domain.contracts import Contract, JobAccepted
from app.private_io.types import StorageError
from app.studio import service
from app.studio.types import AnnotationCreate, AnnotationEdit, AnnotationList, AnnotationView

router = APIRouter(prefix="/v1/admin/studio", dependencies=[Depends(require_admin)])
Admin = Annotated[Principal, Depends(require_admin)]
T = TypeVar("T", bound=BaseModel)
_crop_slots = asyncio.Semaphore(2)


class SourceList(Contract):
    documents: list[AssessmentListItem]


class SourcePages(Contract):
    document_id: UUID
    pages: list[PageView]


async def body(request: Request, model: type[T]) -> T:
    data = bytearray()
    async for chunk in request.stream():
        if len(data) + len(chunk) > 96 * 1024:
            raise HTTPException(413, "Annotation exceeds the size limit")
        data.extend(chunk)
    try:
        return model.model_validate_json(data)
    except ValidationError:
        raise HTTPException(422, "Invalid annotation fields") from None


def boundary(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, "Source or annotation not found")
    if isinstance(exc, service.Conflict):
        return HTTPException(409, "Annotation changed or retry conflicts; reload before saving")
    if isinstance(exc, ValueError):
        return HTTPException(422, "Invalid source box or annotation")
    return HTTPException(503, "Private source unavailable")


@router.get("/sources", response_model=SourceList)
def sources(principal: Admin) -> SourceList:
    return SourceList(documents=service.recent(principal))


@router.post("/sources/{document_id}/render", response_model=JobAccepted, status_code=202)
def render(document_id: UUID, principal: Admin) -> JobAccepted:
    try:
        return service.prepare(principal, document_id)
    except (LookupError, StorageError) as exc:
        raise boundary(exc) from None


@router.get("/sources/{document_id}/pages", response_model=SourcePages)
def pages(document_id: UUID, principal: Admin) -> SourcePages:
    try:
        return SourcePages(document_id=document_id, pages=service.pages(principal, document_id))
    except (LookupError, StorageError) as exc:
        raise boundary(exc) from None


@router.get("/sources/{document_id}/pages/{number}/image", response_class=Response)
def image(
    document_id: UUID, number: Annotated[int, Path(ge=1, le=200)], principal: Admin
) -> Response:
    try:
        data = service.image(principal, document_id, number)
        return png(data)
    except (LookupError, StorageError) as exc:
        raise boundary(exc) from None


def png(data: bytes) -> Response:
    return Response(
        data,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/sources/{document_id}/annotations", response_model=AnnotationList)
def annotations(document_id: UUID, principal: Admin) -> AnnotationList:
    try:
        return AnnotationList(annotations=service.annotations(principal, document_id))
    except (LookupError, StorageError) as exc:
        raise boundary(exc) from None


@router.post("/sources/{document_id}/annotations", response_model=AnnotationView, status_code=201)
async def create(document_id: UUID, principal: Admin, request: Request) -> AnnotationView:
    payload = await body(request, AnnotationCreate)
    try:
        await asyncio.wait_for(_crop_slots.acquire(), timeout=0.1)
    except TimeoutError:
        raise HTTPException(429, "Annotation crop capacity is busy") from None
    try:
        return await run_in_threadpool(service.create, principal, document_id, payload)
    except (LookupError, StorageError, ValueError, service.Conflict) as exc:
        raise boundary(exc) from None
    finally:
        _crop_slots.release()


@router.patch("/sources/{document_id}/annotations/{annotation_id}", response_model=AnnotationView)
async def edit(
    document_id: UUID, annotation_id: UUID, principal: Admin, request: Request
) -> AnnotationView:
    payload = await body(request, AnnotationEdit)
    try:
        return await run_in_threadpool(service.edit, principal, document_id, annotation_id, payload)
    except (LookupError, StorageError, ValueError, service.Conflict) as exc:
        raise boundary(exc) from None


@router.get("/sources/{document_id}/annotations/{annotation_id}/crop", response_class=Response)
def crop(document_id: UUID, annotation_id: UUID, principal: Admin) -> Response:
    try:
        return png(service.crop(principal, document_id, annotation_id))
    except (LookupError, StorageError) as exc:
        raise boundary(exc) from None


@router.delete("/sources/{document_id}", status_code=204)
def delete_source(document_id: UUID, principal: Admin) -> Response:
    return remove(principal, document_id)


@router.post("/sources/{document_id}/restore", status_code=204)
def restore_source(document_id: UUID, principal: Admin) -> Response:
    return remove(principal, document_id, restore=True)


@router.delete("/sources/{document_id}/pages/{number}", status_code=204)
def delete_page(
    document_id: UUID, number: Annotated[int, Path(ge=1, le=200)], principal: Admin
) -> Response:
    return remove(principal, document_id, page=number)


@router.post("/sources/{document_id}/pages/{number}/restore", status_code=204)
def restore_page(
    document_id: UUID, number: Annotated[int, Path(ge=1, le=200)], principal: Admin
) -> Response:
    return remove(principal, document_id, page=number, restore=True)


@router.delete("/sources/{document_id}/annotations/{annotation_id}", status_code=204)
def delete_annotation(document_id: UUID, annotation_id: UUID, principal: Admin) -> Response:
    return remove(principal, document_id, annotation=annotation_id)


@router.post("/sources/{document_id}/annotations/{annotation_id}/restore", status_code=204)
def restore_annotation(document_id: UUID, annotation_id: UUID, principal: Admin) -> Response:
    return remove(principal, document_id, annotation=annotation_id, restore=True)


def remove(
    principal: Principal,
    document: UUID,
    *,
    page: int | None = None,
    annotation: UUID | None = None,
    restore: bool = False,
) -> Response:
    try:
        service.remove(principal, document, page=page, annotation=annotation, restore=restore)
    except (LookupError, StorageError, ValueError) as exc:
        raise boundary(exc) from None
    return Response(status_code=204)
