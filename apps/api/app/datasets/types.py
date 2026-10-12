from typing import Annotated, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.contracts import BoundingBox, Contract
from app.studio.types import AnnotationContent

Partition = Literal["development", "holdout"]
Sha = Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]


class SafetyReview(Contract):
    origin: Literal["synthetic", "licensed", "consented_maintainer_material"]
    rights_confirmed: Literal[True]
    text_deidentified: Literal[True]
    crop_reviewed: Literal[True]
    consent_reference: Annotated[str, Field(pattern=r"^consent-[a-z0-9-]{1,64}$")] | None = None

    @model_validator(mode="after")
    def consent_required(self) -> "SafetyReview":
        if self.origin == "consented_maintainer_material" and not self.consent_reference:
            raise ValueError("consent reference required")
        return self


class SourceLocator(Contract):
    sha256: Sha
    page_number: Annotated[int, Field(strict=True, ge=1, le=200)]
    bbox: BoundingBox
    render_version: Annotated[str, Field(min_length=1, max_length=100)]
    crop_sha256: Sha


class CaseRecord(Contract):
    record_type: Literal["annotation_case"] = "annotation_case"
    case_id: UUID
    partition: Partition
    label_origin: Literal["maintainer", "assistant_draft"]
    label_state: Literal["draft", "approved"] = "draft"
    source: SourceLocator
    annotation_revision: Annotated[int, Field(strict=True, ge=1)]
    labels: AnnotationContent
    safety: SafetyReview


class DatasetCreate(Contract):
    name: Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9 _-]+$")]
    version: Annotated[str, Field(min_length=1, max_length=32, pattern=r"^[A-Za-z0-9._-]+$")]
    client_dataset_id: UUID


class CaseAdd(Contract):
    document_id: UUID
    annotation_id: UUID
    expected_revision: Annotated[int, Field(strict=True, ge=1)]
    partition: Partition
    label_origin: Literal["maintainer", "assistant_draft"] = "maintainer"
    safety: SafetyReview


class CaseReview(Contract):
    labels_reviewed: Literal[True]


class DatasetView(Contract):
    id: UUID
    name: str
    version: str
    development: int
    holdout: int
    approved: int


class DatasetList(Contract):
    datasets: list[DatasetView]


class DatasetCases(Contract):
    cases: list[CaseRecord]


class DatasetImport(Contract):
    jsonl: Annotated[str, Field(min_length=1, max_length=5 * 1024 * 1024)]
    safety_reconfirmed: Literal[True]


class ImportResult(Contract):
    imported: int
    reused: int
