from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.contracts import BoundingBox, Contract

Note = Annotated[str, Field(max_length=8000)]


class AnnotationContent(Contract):
    question: Annotated[str, Field(min_length=1, max_length=8000)]
    response: Note = ""
    marks_awarded: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] | None = None
    marks_possible: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] | None = None
    first_error: Note = ""
    observed_behaviours: Note = ""
    observation_status: Literal["observed", "inferred", "not_observed"] = "not_observed"
    intervention: Note = ""
    rationale: Note = ""

    @field_validator("marks_awarded", "marks_possible", mode="before")
    @classmethod
    def numeric_marks(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("marks must be numeric")
        return value

    @model_validator(mode="after")
    def evidence_consistency(self) -> Self:
        if (
            self.marks_awarded is not None
            and self.marks_possible is not None
            and self.marks_awarded > self.marks_possible
        ):
            raise ValueError("awarded marks exceed possible marks")
        if self.observed_behaviours and self.observation_status == "not_observed":
            raise ValueError("behaviour note requires observed/inferred status")
        if self.observation_status != "not_observed" and not self.observed_behaviours:
            raise ValueError("observation status requires a note")
        if self.intervention and not self.rationale:
            raise ValueError("intervention requires rationale")
        return self


class AnnotationCreate(AnnotationContent):
    client_annotation_id: UUID
    page_number: Annotated[int, Field(ge=1, le=200)]
    bbox: BoundingBox


class AnnotationEdit(AnnotationContent):
    expected_revision: Annotated[int, Field(strict=True, ge=1)]


class AnnotationView(AnnotationContent):
    id: UUID
    document_id: UUID
    region_id: UUID
    page_number: int
    bbox: BoundingBox
    revision: int
    source_sha256: str
    render_version: str


class AnnotationList(Contract):
    annotations: list[AnnotationView]
