import json
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.datasets.jsonl import parse_jsonl, question_hash, serialize
from app.datasets.types import CaseRecord, SafetyReview


def fixture() -> CaseRecord:
    return CaseRecord.model_validate(
        {
            "case_id": str(uuid4()),
            "partition": "development",
            "label_origin": "assistant_draft",
            "annotation_revision": 2,
            "source": {
                "sha256": "a" * 64,
                "page_number": 1,
                "bbox": {"x": 0, "y": 0, "width": 20, "height": 10},
                "render_version": "test-v1",
                "crop_sha256": "b" * 64,
            },
            "labels": {
                "question": "Solve x^2 - 4 = 0.",
                "response": "x = 2",
                "first_error": "Negative root missing",
            },
            "safety": {
                "origin": "synthetic",
                "rights_confirmed": True,
                "text_deidentified": True,
                "crop_reviewed": True,
            },
        }
    )


def test_round_trip_and_portable_fields():
    case = fixture()
    assert parse_jsonl(serialize([case])) == [case]
    serialized = serialize([case])
    for forbidden in ("document_id", "annotation_id", "owner_id", "object_key", "filename", "url"):
        assert forbidden not in serialized
    assert case.label_state == "draft" and case.annotation_revision == 2


@pytest.mark.parametrize(
    "mutation",
    [
        {"schema_version": 2},
        {"student_id": str(uuid4())},
        {"label_state": "published"},
        {"partition": "test"},
        {"annotation_revision": True},
    ],
)
def test_unknown_or_unsafe_contract_fields_rejected(mutation):
    with pytest.raises(ValidationError):
        parse_jsonl(json.dumps({**fixture().model_dump(mode="json"), **mutation}))


@pytest.mark.parametrize(
    "response", ["Contact abc@example.test", "https://example.test/private", "Call 416-555-0199"]
)
def test_identifying_text_requires_correction(response):
    case = fixture()
    case.labels.response = response
    with pytest.raises(ValueError, match="identifying"):
        serialize([case])


def test_duplicate_keys_and_ids_and_bounds():
    line = serialize([fixture()]).strip()
    for archive in (
        line + "\n" + line,
        line.replace("{", '{"schema_version":1,', 1),
        "\n",
        line + "\n\n",
        "x" * (5 * 1024 * 1024 + 1),
    ):
        with pytest.raises(ValueError):
            parse_jsonl(archive)


def test_question_normalization_covers_response_variants():
    assert question_hash(" SOLVE  X² - 4 = 0. ") == question_hash("solve x2 - 4 = 0.")
    assert question_hash("Solve x^2 - 4 = 0.") != question_hash("Solve x^2 - 9 = 0.")


def test_consent_requires_opaque_reference():
    base = {
        "origin": "consented_maintainer_material",
        "rights_confirmed": True,
        "text_deidentified": True,
        "crop_reviewed": True,
    }
    with pytest.raises(ValidationError):
        SafetyReview.model_validate(base)
    assert SafetyReview.model_validate({**base, "consent_reference": "consent-reviewed-1"})
    for change in ({"rights_confirmed": False}, {"consent_reference": "person@example.test"}):
        with pytest.raises(ValidationError):
            SafetyReview.model_validate({**base, **change})


def test_synthetic_pack_sources_cover_all_proposals_and_replay_stably(tmp_path):
    import hashlib

    import pymupdf

    from scripts.seed_annotation_dataset import prepare

    cases = prepare(tmp_path)
    assert len(cases) == 40
    assert len({case["family"] for case in cases}) == 10
    sets = {}
    hashes = {}
    for partition, count in (("development", 30), ("holdout", 10)):
        selected = [case for case in cases if case["partition"] == partition]
        sets[partition] = {question_hash(case["labels"]["question"]) for case in selected}
        path = tmp_path / f"synthetic-{partition}-v1.pdf"
        hashes[partition] = hashlib.sha256(path.read_bytes()).hexdigest()
        with pymupdf.open(path) as pdf:
            assert len(pdf) == count
            for case in selected:
                text = pdf[case["page_number"] - 1].get_text()
                assert case["labels"]["question"] in text
                assert case["labels"]["response"] in text
                assert case["correct_answer"] in text
                assert case["labels"]["first_error"] in text.replace("\n", " ")
                assert case["source_sha256"] == hashes[partition]
    assert not sets["development"] & sets["holdout"]
    assert hashes["development"] != hashes["holdout"]
    assert prepare(tmp_path) == cases
