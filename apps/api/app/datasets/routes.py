import asyncio
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, ValidationError
from starlette.concurrency import run_in_threadpool
from starlette.responses import Response

from app.auth.identity import Principal, require_admin
from app.datasets import service
from app.datasets.types import (
    CaseAdd,
    CaseRecord,
    CaseReview,
    DatasetCases,
    DatasetCreate,
    DatasetImport,
    DatasetList,
    DatasetView,
    ImportResult,
    Partition,
)
from app.private_io.types import StorageError
from app.studio.service import Conflict

router = APIRouter(prefix="/v1/admin/studio/datasets", dependencies=[Depends(require_admin)])
Admin = Annotated[Principal, Depends(require_admin)]
_slots = asyncio.Semaphore(1)


def boundary(exc: Exception) -> HTTPException:
    if isinstance(exc, LookupError):
        return HTTPException(404, "Dataset, case or matching owned source PDF not found")
    if isinstance(exc, Conflict):
        return HTTPException(409, "Dataset conflict: check identity, split and label approval")
    if isinstance(exc, ValueError):
        return HTTPException(
            422, "Invalid dataset: check schema, privacy review and source integrity"
        )
    return HTTPException(503, "Private source unavailable")


async def body(request: Request, model: type[BaseModel]) -> BaseModel:
    data = bytearray()
    try:
        async with asyncio.timeout(30):
            async for chunk in request.stream():
                if len(data) + len(chunk) > (
                    6 * 1024 * 1024 if model is DatasetImport else 96 * 1024
                ):
                    raise HTTPException(413, "Dataset request exceeds size limit")
                data.extend(chunk)
        return model.model_validate_json(data)
    except ValidationError:
        raise HTTPException(422, "Invalid dataset fields") from None
    except TimeoutError:
        raise HTTPException(408, "Dataset request timed out") from None


@router.get("", response_model=DatasetList)
def recent(principal: Admin) -> DatasetList:
    return DatasetList(datasets=service.recent(principal))


@router.post("", response_model=DatasetView, status_code=201)
async def create(principal: Admin, request: Request) -> DatasetView:
    payload = DatasetCreate.model_validate(await body(request, DatasetCreate))
    try:
        return await run_in_threadpool(service.create, principal, payload)
    except (LookupError, ValueError, StorageError, Conflict) as exc:
        raise boundary(exc) from None


@router.get("/{dataset_id}/cases", response_model=DatasetCases)
def cases(dataset_id: UUID, principal: Admin) -> DatasetCases:
    try:
        return DatasetCases(cases=service.cases(principal, dataset_id))
    except LookupError as exc:
        raise boundary(exc) from None


@router.get("/{dataset_id}/cases/{case_id}/crop")
def crop(dataset_id: UUID, case_id: UUID, principal: Admin) -> Response:
    try:
        data = service.crop(principal, dataset_id, case_id)
    except (LookupError, ValueError, StorageError) as exc:
        raise boundary(exc) from None
    return Response(data, media_type="image/png", headers={"Cache-Control": "no-store"})


@router.post("/{dataset_id}/cases", response_model=CaseRecord, status_code=201)
async def add(dataset_id: UUID, principal: Admin, request: Request) -> CaseRecord:
    payload = CaseAdd.model_validate(await body(request, CaseAdd))
    try:
        return await run_in_threadpool(service.add, principal, dataset_id, payload)
    except (LookupError, ValueError, StorageError, Conflict) as exc:
        raise boundary(exc) from None


@router.post("/{dataset_id}/cases/{case_id}/review", status_code=204)
async def review(dataset_id: UUID, case_id: UUID, principal: Admin, request: Request) -> Response:
    await body(request, CaseReview)
    try:
        await run_in_threadpool(service.approve, principal, dataset_id, case_id)
    except (LookupError, ValueError) as exc:
        raise boundary(exc) from None
    return Response(status_code=204)


@router.get("/{dataset_id}/export")
def export(
    dataset_id: UUID,
    principal: Admin,
    partition: Annotated[Partition, Query()],
    preview: bool = False,
) -> Response:
    try:
        data = service.export(principal, dataset_id, partition, preview)
    except (LookupError, ValueError, Conflict) as exc:
        raise boundary(exc) from None
    return Response(
        data,
        media_type="application/x-ndjson",
        headers={
            "Content-Disposition": f'attachment; filename="{partition}-annotations-v1.jsonl"',
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/{dataset_id}/import", response_model=ImportResult)
async def import_archive(dataset_id: UUID, principal: Admin, request: Request) -> ImportResult:
    payload = DatasetImport.model_validate(await body(request, DatasetImport))
    try:
        await asyncio.wait_for(_slots.acquire(), timeout=0.1)
    except TimeoutError:
        raise HTTPException(429, "Dataset import capacity is busy") from None
    try:
        return await run_in_threadpool(service.import_archive, principal, dataset_id, payload.jsonl)
    except (LookupError, ValueError, StorageError, Conflict) as exc:
        raise boundary(exc) from None
    finally:
        _slots.release()
