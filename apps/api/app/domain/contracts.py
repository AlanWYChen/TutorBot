from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.limits import MAX_DOCUMENT_PAGES, MAX_UPLOAD_BYTES

Probability = Annotated[float, Field(ge=0, le=1, allow_inf_nan=False)]
ShortText = Annotated[str, Field(min_length=1, max_length=256)]
Content = Annotated[str, Field(min_length=1, max_length=20000)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    schema_version: Literal[1] = 1


class ReleaseStatus(StrEnum):
    DRAFT = "draft"
    EVALUATING = "evaluating"
    APPROVED = "approved"
    PUBLISHED = "published"
    RETIRED = "retired"


class AssignmentType(StrEnum):
    UNKNOWN = "unknown"
    HOMEWORK = "ordinary_homework"
    TEST = "marked_test"
    EXAM = "exam"
    IB_MATH_IA = "IB_math_IA"


class JobState(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_WAIT = "retry_wait"
    NEEDS_REVIEW = "needs_review"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


class EvidenceRef(Contract):
    source_type: Literal[
        "document_region",
        "concept_evidence",
        "mistake_observation",
        "fingerprint_observation",
        "tutoring_message",
        "profile_revision",
    ]
    source_id: UUID
    confidence: Probability
    explanation: ShortText


class ContextEvidence(Contract):
    field: Literal[
        "subject",
        "program",
        "course",
        "level",
        "assessment_cohort",
        "curriculum_version",
        "assignment_type",
        "stage",
        "topics",
    ]
    source: Literal["student_confirmation", "document", "published_metadata"]
    source_id: UUID | None = None
    description: ShortText
    confidence: Probability


ContextField = Literal[
    "subject",
    "program",
    "course",
    "level",
    "assessment_cohort",
    "curriculum_version",
    "assignment_type",
    "stage",
    "topics",
]


class ResolvedLearningContext(Contract):
    subject: ShortText | None = None
    program: ShortText | None = None
    course: ShortText | None = None
    level: ShortText | None = None
    assessment_cohort: Annotated[int, Field(ge=1900, le=2200)] | None = None
    curriculum_version: ShortText | None = None
    assignment_type: AssignmentType | None = None
    stage: ShortText | None = None
    topics: Annotated[list[ShortText], Field(max_length=50)] = Field(default_factory=list)
    confidence: Probability = 0
    evidence: Annotated[list[ContextEvidence], Field(max_length=100)] = Field(default_factory=list)
    unresolved_fields: Annotated[list[ContextField], Field(max_length=9)] = Field(
        default_factory=list
    )

    @model_validator(mode="after")
    def record_unknowns(self) -> Self:
        fields: tuple[ContextField, ...] = (
            "subject",
            "program",
            "course",
            "level",
            "assessment_cohort",
            "curriculum_version",
            "assignment_type",
            "stage",
            "topics",
        )
        unknown = [
            name
            for name in fields
            if getattr(self, name) is None
            or (name == "topics" and not self.topics)
            or (name == "assignment_type" and self.assignment_type == AssignmentType.UNKNOWN)
        ]
        self.unresolved_fields = list(dict.fromkeys([*self.unresolved_fields, *unknown]))
        return self


class UploadMetadata(Contract):
    filename: Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[^/\\\x00-\x1f]+$")]
    media_type: Literal["application/pdf", "image/png", "image/jpeg"]
    size_bytes: Annotated[int, Field(strict=True, gt=0, le=MAX_UPLOAD_BYTES)]
    sha256: Sha256
    page_count: Annotated[int, Field(strict=True, ge=1, le=MAX_DOCUMENT_PAGES)] | None = None


class AssessmentUpload(UploadMetadata):
    assessment_type: AssignmentType
    curriculum_id: UUID | None = None


class CohortRange(Contract):
    first_assessment: Annotated[int, Field(ge=1900, le=2200)]
    last_assessment: Annotated[int, Field(ge=1900, le=2200)] | None = None

    @model_validator(mode="after")
    def ordered(self) -> Self:
        if self.last_assessment is not None and self.last_assessment < self.first_assessment:
            raise ValueError("cohort range must be ordered")
        return self


class KnowledgeUpload(UploadMetadata):
    page_count: Annotated[int, Field(strict=True, ge=1, le=MAX_DOCUMENT_PAGES)]
    title: ShortText
    author: ShortText
    publisher: ShortText
    source_url: Annotated[str, Field(max_length=2048, pattern=r"^https://")] | None = None
    kind: Literal["curriculum", "textbook", "rubric", "reference"]
    source_authority: Literal["official", "supplemental"]
    license_metadata: Annotated[dict[str, ShortText], Field(min_length=1, max_length=20)]
    curriculum_id: UUID | None = None
    cohort_range: CohortRange | None = None


class JobAccepted(Contract):
    job_id: UUID
    resource_id: UUID
    status: JobState


class AssessmentStatus(Contract):
    assessment_id: UUID
    job_id: UUID | None = None
    status: JobState
    verified_state: Literal["unverified", "needs_review", "verified"]
    page_count: Annotated[int, Field(ge=0, le=MAX_DOCUMENT_PAGES)]
    error_code: Literal["invalid_document", "page_limit", "processing_failed"] | None = None


class KnowledgeUploadStatus(Contract):
    document_id: UUID
    job_id: UUID
    status: JobState
    page_count: Annotated[int, Field(ge=1, le=MAX_DOCUMENT_PAGES)]
    processing_kind: Literal["storage_verification"] = "storage_verification"


class BoundingBox(Contract):
    """Coordinates in rendered page pixels; page dimensions bound them at ingestion."""

    x: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    y: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    width: Annotated[float, Field(gt=0, allow_inf_nan=False)]
    height: Annotated[float, Field(gt=0, allow_inf_nan=False)]


class RegionLocator(Contract):
    region_id: UUID
    page_number: Annotated[int, Field(ge=1, le=MAX_DOCUMENT_PAGES)]
    bbox: BoundingBox
    confidence: Probability


class QuestionView(Contract):
    id: UUID
    prompt_text: Content
    region: RegionLocator
    concept_ids: Annotated[list[UUID], Field(max_length=50)]
    marks_possible: Annotated[float, Field(ge=0, le=1000, allow_inf_nan=False)] | None = None
    response_text: Content | None = None
    correctness_status: Literal["unknown", "correct", "partially_correct", "incorrect"]
    evidence: Annotated[list[EvidenceRef], Field(max_length=100)]


class AssessmentQuestions(Contract):
    assessment_id: UUID
    questions: Annotated[list[QuestionView], Field(max_length=500)]


class QuestionCorrection(Contract):
    """Path IDs identify the question; scope comes exclusively from authentication."""

    supersedes_observation_id: UUID
    corrected_text: Content
    reason: Annotated[str, Field(min_length=1, max_length=2000)]
    source_region_id: UUID


class CorrectionAccepted(Contract):
    correction_id: UUID
    review_status: Literal["unreviewed", "verified", "rejected"]


class LearningState(Contract):
    definition_id: UUID
    course_id: UUID | None = None
    context_scope: ShortText
    level: Literal[
        "proficient", "developing", "needs_support", "not_observed", "insufficient_evidence"
    ]
    trend: Literal["unknown", "stable", "improving", "declining"] = "unknown"
    evidence_count: Annotated[int, Field(ge=0)] = 0
    uncertainty: Probability
    evidence: Annotated[list[EvidenceRef], Field(max_length=100)] = Field(default_factory=list)
    updated_at: datetime

    @model_validator(mode="after")
    def no_unsupported_state(self) -> Self:
        if self.evidence_count == 0 and self.level not in {"not_observed", "insufficient_evidence"}:
            raise ValueError("a demonstrated state requires evidence")
        return self


class StudentLearningContext(Contract):
    profile_id: UUID | None = None
    subject_id: UUID
    current_summary: Annotated[str, Field(max_length=10000)] | None = None
    summary_version: Annotated[int, Field(ge=0)] = 0
    revision_id: UUID | None = None
    concept_states: Annotated[list[LearningState], Field(max_length=500)] = Field(
        default_factory=list
    )
    trait_states: Annotated[list[LearningState], Field(max_length=100)] = Field(
        default_factory=list
    )
    evidence: Annotated[list[EvidenceRef], Field(max_length=100)] = Field(default_factory=list)


class ProfileResponse(Contract):
    subjects: Annotated[list[StudentLearningContext], Field(max_length=20)]


class FingerprintResponse(Contract):
    subject_id: UUID
    traits: Annotated[list[LearningState], Field(max_length=100)]
    interpretation: Literal["observable_work_habits"] = "observable_work_habits"


class ClassifyAssignment(Contract):
    document_id: UUID
    confirmed_context: ResolvedLearningContext | None = None


class AssignmentClassification(Contract):
    assignment_id: UUID
    context: ResolvedLearningContext
    confirmation_required: bool


class CreateTutorSession(Contract):
    assignment_id: UUID | None = None
    context: ResolvedLearningContext


class TutorSessionCreated(Contract):
    session_id: UUID
    skill_release_id: UUID
    knowledge_release_id: UUID
    created_at: datetime


class TutorMessageRequest(Contract):
    content: Annotated[str, Field(min_length=1, max_length=8000)]
    client_message_id: UUID


class TutorMessageResponse(Contract):
    message_id: UUID
    content: Content
    citations: Annotated[list[EvidenceRef], Field(max_length=100)]
    created_at: datetime


class ProcessKnowledge(Contract):
    expected_sha256: Sha256


class PublishCandidate(Contract):
    document_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    manifest_hash: Sha256


class AdminAnnotation(Contract):
    """Only maintainer document regions are accepted by the eventual handler."""

    region_id: UUID
    annotation: Content
    rationale: Content


class DemonstrationCreate(Contract):
    source_document_id: UUID
    concept_id: UUID | None = None
    scenario: Content
    intervention: Content
    rationale: Content


class SkillProposal(Contract):
    base_skill_version_id: UUID | None = None
    name: ShortText
    version: ShortText
    demonstration_ids: Annotated[list[UUID], Field(min_length=1, max_length=100)]
    proposed_content: Content
    content_hash: Sha256


class EvaluateSkill(Contract):
    knowledge_release_id: UUID
    case_ids: Annotated[list[UUID], Field(min_length=1, max_length=500)]


class PublishRelease(Contract):
    skill_version_id: UUID
    knowledge_release_id: UUID
    evaluation_run_id: UUID
    expected_manifest_hash: Sha256


class EvaluationResult(Contract):
    run_id: UUID
    release_candidate: UUID
    verdict: Literal["pending", "passed", "failed"]
    metric_results: Annotated[dict[str, Probability], Field(max_length=100)]
    created_at: datetime


class EvaluationList(Contract):
    evaluations: Annotated[list[EvaluationResult], Field(max_length=100)]
    next_cursor: UUID | None = None


class ResourceCreated(Contract):
    resource_id: UUID
    status: ReleaseStatus


# Contract catalog, not mounted routes. Multipart upload handlers also validate the binary.
ENDPOINT_CONTRACTS: dict[str, tuple[type[Contract] | None, type[Contract]]] = {
    "POST /v1/student/assessments/upload": (AssessmentUpload, JobAccepted),
    "GET /v1/student/assessments/{id}/status": (None, AssessmentStatus),
    "GET /v1/student/assessments/{id}/questions": (None, AssessmentQuestions),
    "PATCH /v1/student/assessments/{id}/questions/{qid}/corrections": (
        QuestionCorrection,
        CorrectionAccepted,
    ),
    "GET /v1/student/profile": (None, ProfileResponse),
    "GET /v1/student/fingerprint": (None, FingerprintResponse),
    "POST /v1/student/assignments/classify": (ClassifyAssignment, AssignmentClassification),
    "POST /v1/student/tutor/sessions": (CreateTutorSession, TutorSessionCreated),
    "POST /v1/student/tutor/sessions/{id}/messages": (TutorMessageRequest, TutorMessageResponse),
    "POST /v1/admin/knowledge/upload": (KnowledgeUpload, JobAccepted),
    "GET /v1/admin/knowledge/{id}/status": (None, KnowledgeUploadStatus),
    "POST /v1/admin/knowledge/{id}/process": (ProcessKnowledge, JobAccepted),
    "POST /v1/admin/knowledge/{id}/publish-candidate": (PublishCandidate, JobAccepted),
    "POST /v1/admin/annotations": (AdminAnnotation, ResourceCreated),
    "POST /v1/admin/demonstrations": (DemonstrationCreate, ResourceCreated),
    "POST /v1/admin/skills/proposals": (SkillProposal, JobAccepted),
    "POST /v1/admin/skills/{id}/evaluate": (EvaluateSkill, JobAccepted),
    "POST /v1/admin/releases/publish": (PublishRelease, ResourceCreated),
    "GET /v1/admin/evaluations": (None, EvaluationList),
}
