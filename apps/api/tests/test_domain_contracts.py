from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.domain.contracts import (
    MAX_UPLOAD_BYTES,
    AssessmentUpload,
    CohortRange,
    LearningState,
    ResolvedLearningContext,
    TutorMessageRequest,
)


def test_unknown_context_does_not_guess_course_or_rubric() -> None:
    context = ResolvedLearningContext(subject="Mathematics")
    assert context.curriculum_version is None
    assert context.assessment_cohort is None
    assert context.confidence == 0
    assert "curriculum_version" in context.unresolved_fields
    assert "assessment_cohort" in context.unresolved_fields
    assert "subject" not in context.unresolved_fields


@pytest.mark.parametrize(
    "changes",
    [
        {"size_bytes": MAX_UPLOAD_BYTES + 1},
        {"page_count": 201},
        {"size_bytes": True},
        {"filename": "../private.pdf"},
        {"sha256": "not-a-hash"},
        {"media_type": "text/html"},
        {"student_id": str(uuid4())},
    ],
)
def test_upload_limits_and_untrusted_scope_rejected(changes: dict[str, object]) -> None:
    payload = dict(
        filename="test.pdf",
        media_type="application/pdf",
        size_bytes=1000,
        sha256="a" * 64,
        page_count=1,
        assessment_type="marked_test",
    )
    payload.update(changes)
    with pytest.raises(ValidationError):
        AssessmentUpload.model_validate(payload)


def test_fingerprint_cannot_claim_mastery_without_evidence() -> None:
    base = dict(
        definition_id=uuid4(),
        context_scope="algebra",
        updated_at=datetime.now(UTC),
        uncertainty=1,
        evidence_count=0,
    )
    state = LearningState.model_validate(dict(base, level="insufficient_evidence"))
    assert state.level == "insufficient_evidence"
    with pytest.raises(ValidationError):
        LearningState.model_validate(dict(base, level="proficient"))
    with pytest.raises(ValidationError):
        LearningState.model_validate(dict(base, level="confident_personality"))


def test_invalid_cohort_message_and_scope_are_rejected() -> None:
    with pytest.raises(ValidationError):
        CohortRange(first_assessment=2028, last_assessment=2026)
    for content in ["", "x" * 8001]:
        with pytest.raises(ValidationError):
            TutorMessageRequest(content=content, client_message_id=uuid4())
    with pytest.raises(ValidationError):
        TutorMessageRequest.model_validate(
            dict(content="Help", client_message_id=uuid4(), student_id=uuid4())
        )
