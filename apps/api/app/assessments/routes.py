from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Path
from starlette.responses import Response

from app.assessments import service
from app.assessments.types import AssessmentList, AssessmentPages
from app.auth.identity import Principal, require_student
from app.domain.contracts import JobAccepted
from app.private_io.types import StorageError

router = APIRouter(prefix="/v1/student/assessments", dependencies=[Depends(require_student)])
Student = Annotated[Principal, Depends(require_student)]


@router.get("", response_model=AssessmentList)
def recent(principal: Student) -> AssessmentList:
    return service.recent(principal)


@router.post("/{assessment_id}/render", response_model=JobAccepted, status_code=202)
def render(assessment_id: UUID, principal: Student) -> JobAccepted:
    try:
        return service.prepare(principal, assessment_id)
    except LookupError:
        raise HTTPException(404, "Assessment not found") from None


@router.get("/{assessment_id}/pages", response_model=AssessmentPages)
def pages(assessment_id: UUID, principal: Student) -> AssessmentPages:
    try:
        return service.pages(principal, assessment_id)
    except LookupError:
        raise HTTPException(404, "Assessment not found") from None


@router.get(
    "/{assessment_id}/pages/{page_number}/image",
    response_class=Response,
    responses={200: {"content": {"image/png": {"schema": {"type": "string", "format": "binary"}}}}},
)
def image(
    assessment_id: UUID, page_number: Annotated[int, Path(ge=1, le=200)], principal: Student
) -> Response:
    try:
        data = service.page_image(principal, assessment_id, page_number)
    except LookupError:
        raise HTTPException(404, "Page not found") from None
    except StorageError:
        raise HTTPException(503, "Page unavailable") from None
    return Response(
        data,
        media_type="image/png",
        headers={
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
            "Content-Disposition": 'inline; filename="page.png"',
        },
    )
