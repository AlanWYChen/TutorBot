from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field

from app.domain.contracts import BoundingBox, Contract, JobState

RENDER_VERSION = "mupdf-1.28.2-scale-1.5-v1"
RENDER_SCALE = 1.5


class CandidateView(Contract):
    id: UUID
    label: str
    bbox: BoundingBox
    confidence: Annotated[float, Field(ge=0.5, le=0.5)] = 0.5
    status: Literal["candidate"] = "candidate"


class PageView(Contract):
    id: UUID
    page_number: int
    width: int
    height: int
    rotation: int
    render_version: str
    candidates: list[CandidateView]


class AssessmentPages(Contract):
    assessment_id: UUID
    pages: list[PageView]


class AssessmentListItem(Contract):
    id: UUID
    filename: str
    page_count: int
    state: JobState | Literal["not_prepared"]


class AssessmentList(Contract):
    assessments: list[AssessmentListItem]


class RenderedCandidate(Contract):
    number: Annotated[int, Field(ge=1, le=999)]
    bbox: BoundingBox


class RenderedPage(Contract):
    page_number: Annotated[int, Field(ge=1, le=200)]
    width: Annotated[int, Field(gt=0, le=10000)]
    height: Annotated[int, Field(gt=0, le=10000)]
    rotation: Literal[0, 90, 180, 270]
    candidates: Annotated[list[RenderedCandidate], Field(max_length=100)]


class RenderResult(Contract):
    pages: Annotated[list[RenderedPage], Field(min_length=1, max_length=200)]
