import hashlib
import json
import re
import unicodedata

from app.datasets.types import CaseRecord

MAX_ARCHIVE_BYTES = 5 * 1024 * 1024
MAX_CASES = 50


def question_hash(question: str) -> str:
    canonical = " ".join(unicodedata.normalize("NFKC", question).casefold().split())
    return hashlib.sha256(canonical.encode()).hexdigest()


def privacy_check(record: CaseRecord) -> None:
    # Do not silently rewrite mathematical labels. Require correction/review instead.
    text = "\n".join(
        value for value in record.labels.model_dump().values() if isinstance(value, str)
    )
    if (
        re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", text, re.I)
        or re.search(r"(?:https?://|www\.)", text, re.I)
        or re.search(r"(?<!\w)(?:\+?\d[\s().-]*){9,15}(?!\w)", text)
    ):
        raise ValueError("potential identifying text requires review")


def no_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def parse_jsonl(data: str) -> list[CaseRecord]:
    if len(data.encode()) > MAX_ARCHIVE_BYTES:
        raise ValueError("archive too large")
    lines = data.splitlines()
    if not 1 <= len(lines) <= MAX_CASES or any(not line.strip() for line in lines):
        raise ValueError("archive must contain 1-50 nonempty records")
    records = []
    identities = set()
    for line in lines:
        if len(line.encode()) > 128 * 1024:
            raise ValueError("record too large")
        record = CaseRecord.model_validate(json.loads(line, object_pairs_hook=no_duplicate_keys))
        privacy_check(record)
        if record.case_id in identities:
            raise ValueError("duplicate case ID")
        identities.add(record.case_id)
        records.append(record)
    return records


def serialize(records: list[CaseRecord]) -> str:
    if not 1 <= len(records) <= MAX_CASES:
        raise ValueError("archive must contain 1-50 records")
    for record in records:
        privacy_check(record)
    lines = [record.model_dump_json() + "\n" for record in records]
    if any(len(line.encode()) > 128 * 1024 for line in lines):
        raise ValueError("record too large")
    data = "".join(lines)
    if len(data.encode()) > MAX_ARCHIVE_BYTES:
        raise ValueError("archive too large")
    return data
