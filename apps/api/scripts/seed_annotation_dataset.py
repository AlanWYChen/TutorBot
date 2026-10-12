"""Prepare synthetic assistant drafts; never approve labels or read student sources."""

import hashlib
import json
import sys
import time
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

import httpx
import pymupdf

from app.config import Settings


def examples() -> list[dict]:
    cases = []
    for n in range(2, 6):
        families = [
            (
                "square_roots",
                f"Solve x^2 - {n * n} = 0.",
                f"x = {n}",
                f"x = {n} or x = -{n}",
                "Only the positive root is written.",
                "Ask which two values square to the given constant.",
                "Testing both signs checks the omitted root.",
            ),
            (
                "zero_product",
                f"Solve (x - {n})(x + {n + 1}) = 0.",
                f"x = {n}",
                f"x = {n} or x = -{n + 1}",
                "The second factor's root is missing.",
                "Set each factor equal to zero separately.",
                "Both factors can make the product zero.",
            ),
            (
                "expansion",
                f"Expand (x + {n})(x - 1).",
                f"x^2 + {n + 1}x - {n}",
                f"x^2 + {n - 1}x - {n}",
                "The written middle coefficient is incorrect.",
                "Write the two cross products before combining them.",
                "Separate cross products make the negative term visible.",
            ),
            (
                "vertex",
                f"Find the vertex of y = (x - {n})^2 + {n + 1}.",
                f"({n}, 0)",
                f"({n}, {n + 1})",
                "The vertex's vertical coordinate is incorrect.",
                f"Substitute x = {n} into the function.",
                "Substitution exposes the vertical shift.",
            ),
            (
                "axis",
                f"Find the axis of symmetry of y = (x + {n})^2 - 1.",
                f"x = {n}",
                f"x = -{n}",
                "The written axis has the wrong sign.",
                "Find the x value that makes the squared expression zero.",
                "Solving the inner expression checks the horizontal shift.",
            ),
            (
                "discriminant",
                f"Find the discriminant of x^2 + {n + 2}x + {n} = 0.",
                f"D = ({n + 2})^2 + 4({n}) = {(n + 2) ** 2 + 4 * n}",
                f"D = {n * n + 4}",
                "The response adds 4ac instead of subtracting it.",
                "Write b^2 - 4ac, then substitute a, b and c.",
                "Preserving the subtraction sign corrects the formula.",
            ),
            (
                "intercept",
                f"Find the y-intercept of y = x^2 - {n + 1}x + {n}.",
                f"({n}, 0)",
                f"(0, {n})",
                "The coordinates written for the y-intercept are reversed.",
                "Set x to zero and write the resulting point.",
                "A y-intercept lies on the y-axis.",
            ),
            (
                "common_factor",
                f"Factor {n}x^2 - {n * n}x completely.",
                f"{n}x(x + {n})",
                f"{n}x(x - {n})",
                "The second term inside the factor has the wrong sign.",
                "Divide each original term by the common factor, then expand to check.",
                "Division and expansion verify the sign.",
            ),
            (
                "turning_point",
                f"Classify the turning point of y = -(x - {n})^2 + {n * n}.",
                f"Minimum at ({n}, {n * n})",
                f"Maximum at ({n}, {n * n})",
                "The response labels the turning point as a minimum.",
                "Compare nearby y values with the turning-point value.",
                "The negative square makes nearby values smaller.",
            ),
            (
                "complete_square",
                f"Complete the square: x^2 + {2 * n}x + {n * n + 3}.",
                f"(x + {n})^2",
                f"(x + {n})^2 + 3",
                "The constant adjustment is missing from the written expression.",
                "Expand the proposed square and compare constant terms.",
                "The constant difference identifies the required adjustment.",
            ),
        ]
        for family, question, response, correct, error, intervention, rationale in families:
            partition = "holdout" if n == 5 else "development"
            cases.append(
                {
                    "key": f"{family}-{n}",
                    "family": family,
                    "partition": partition,
                    "correct_answer": correct,
                    "labels": {
                        "schema_version": 1,
                        "question": question,
                        "response": response,
                        "marks_awarded": 1,
                        "marks_possible": 2,
                        "first_error": error,
                        "observed_behaviours": "The visible response is: " + response,
                        "observation_status": "observed",
                        "intervention": intervention,
                        "rationale": rationale,
                    },
                }
            )
    return cases


def prepare(root: Path) -> list[dict]:
    root.mkdir(parents=True, exist_ok=True)
    cases = examples()
    for partition in ("development", "holdout"):
        selected = [case for case in cases if case["partition"] == partition]
        path = root / f"synthetic-{partition}-v1.pdf"
        if not path.exists():
            with pymupdf.open() as doc:
                for page_number, case in enumerate(selected, 1):
                    page = doc.new_page(width=600, height=320)
                    page.insert_text(
                        (50, 22),
                        "SYNTHETIC - assistant draft labels; maintainer review required",
                        fontsize=9,
                    )
                    labels = case["labels"]
                    page.insert_textbox(
                        (50, 45, 550, 105), f"{page_number}. {labels['question']}", fontsize=14
                    )
                    page.insert_textbox(
                        (50, 110, 550, 160), "Response: " + labels["response"], fontsize=13
                    )
                    page.insert_textbox(
                        (50, 175, 550, 300),
                        "Synthetic teacher mark: 1/2\nCorrect answer: "
                        + case["correct_answer"]
                        + "\nFeedback: "
                        + labels["first_error"],
                        fontsize=12,
                        color=(0.8, 0, 0),
                    )
                path.write_bytes(doc.tobytes(no_new_id=True))
        for page_number, case in enumerate(selected, 1):
            case["page_number"] = page_number
            case["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
    (root / "proposed-labels.json").write_text(json.dumps(cases, indent=2) + "\n")
    return cases


def seed(root: Path) -> None:
    settings = Settings()
    if settings.app_env != "local" or not settings.firebase_auth_emulator_host:
        raise RuntimeError("Synthetic dataset requires local emulators")
    cases = prepare(root)
    response = httpx.post(
        f"http://{settings.firebase_auth_emulator_host}/identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key=demo-key",
        json={
            "email": "maintainer@example.test",
            "password": "TutorBot-local-123!",
            "returnSecureToken": True,
        },
    )
    response.raise_for_status()
    headers = {"Authorization": "Bearer " + response.json()["idToken"]}
    with httpx.Client(base_url="http://web:3000/api/studio", headers=headers, timeout=120) as web:
        dataset = web.post(
            "/datasets",
            json={
                "name": "Synthetic quadratic review",
                "version": "v1",
                "client_dataset_id": str(
                    uuid5(NAMESPACE_URL, "tutorbot/p103/synthetic-dataset/v1")
                ),
            },
        )
        dataset.raise_for_status()
        dataset_id = dataset.json()["id"]
        for partition in ("development", "holdout"):
            path = root / f"synthetic-{partition}-v1.pdf"
            data = path.read_bytes()
            sha = hashlib.sha256(data).hexdigest()
            metadata = {
                "filename": path.name,
                "media_type": "application/pdf",
                "size_bytes": len(data),
                "sha256": sha,
                "title": "Synthetic quadratic " + partition,
                "author": "TutorBot synthetic generator",
                "publisher": "Local development",
                "kind": "reference",
                "source_authority": "supplemental",
                "license_metadata": {
                    "rights": "Synthetic source generated for TutorBot; no student data"
                },
            }
            response = web.post(
                "/upload",
                headers={"Idempotency-Key": str(uuid5(NAMESPACE_URL, "tutorbot/p103/" + sha))},
                files={
                    "file": (path.name, data, "application/pdf"),
                    "metadata": (None, json.dumps(metadata)),
                },
            )
            response.raise_for_status()
            doc = response.json()["resource_id"]
            base = "/sources/" + doc
            web.post(base + "/render").raise_for_status()
            deadline = time.monotonic() + 120
            while time.monotonic() < deadline:
                response = web.get(base + "/pages")
                response.raise_for_status()
                if response.json()["pages"]:
                    break
                time.sleep(0.5)
            else:
                raise RuntimeError("Synthetic source render timed out")
            for case in [item for item in cases if item["partition"] == partition]:
                response = web.post(
                    base + "/annotations",
                    json={
                        **case["labels"],
                        "client_annotation_id": str(
                            uuid5(NAMESPACE_URL, "tutorbot/p103/" + case["key"])
                        ),
                        "page_number": case["page_number"],
                        "bbox": {"x": 75, "y": 55, "width": 765, "height": 405},
                    },
                )
                response.raise_for_status()
                note = response.json()
                response = web.post(
                    f"/datasets/{dataset_id}/cases",
                    json={
                        "document_id": doc,
                        "annotation_id": note["id"],
                        "expected_revision": note["revision"],
                        "partition": partition,
                        "label_origin": "assistant_draft",
                        "safety": {
                            "origin": "synthetic",
                            "rights_confirmed": True,
                            "text_deidentified": True,
                            "crop_reviewed": True,
                        },
                    },
                )
                response.raise_for_status()
            response = web.get(
                f"/datasets/{dataset_id}/export", params={"partition": partition, "preview": "true"}
            )
            response.raise_for_status()
            (root / f"{partition}.preview.jsonl").write_text(response.text)
    print("Prepared 30 development and 10 held-out assistant drafts. No labels approved.")


if __name__ == "__main__":
    output = Path(sys.argv[2] if len(sys.argv) > 2 else "/workspace/docs/datasets/synthetic-v1")
    if len(sys.argv) > 1 and sys.argv[1] == "prepare":
        prepare(output)
    else:
        seed(output)
