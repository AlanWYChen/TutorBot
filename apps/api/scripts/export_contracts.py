"""Export the domain catalog; implemented upload operations use multipart metadata."""

import json

from pydantic.json_schema import models_json_schema

from app.datasets.types import (
    CaseAdd,
    CaseRecord,
    DatasetCases,
    DatasetCreate,
    DatasetImport,
    DatasetList,
    DatasetView,
    ImportResult,
)
from app.domain.contracts import ENDPOINT_CONTRACTS
from app.studio.routes import SourceList, SourcePages
from app.studio.types import AnnotationCreate, AnnotationEdit, AnnotationList, AnnotationView


def main() -> None:
    catalog = dict(ENDPOINT_CONTRACTS)
    catalog.update(
        {
            "GET /v1/admin/studio/datasets/{dataset_id}/cases/{case_id}/annotation": (
                None,
                AnnotationView,
            ),
            "GET /v1/admin/studio/datasets": (None, DatasetList),
            "POST /v1/admin/studio/datasets": (DatasetCreate, DatasetView),
            "GET /v1/admin/studio/datasets/{dataset_id}/cases": (None, DatasetCases),
            "POST /v1/admin/studio/datasets/{dataset_id}/cases": (CaseAdd, CaseRecord),
            "POST /v1/admin/studio/datasets/{dataset_id}/import": (DatasetImport, ImportResult),
            "GET /v1/admin/studio/sources": (None, SourceList),
            "GET /v1/admin/studio/sources/{document_id}/pages": (None, SourcePages),
            "GET /v1/admin/studio/sources/{document_id}/annotations": (None, AnnotationList),
            "POST /v1/admin/studio/sources/{document_id}/annotations": (
                AnnotationCreate,
                AnnotationView,
            ),
            "PATCH /v1/admin/studio/sources/{document_id}/annotations/{annotation_id}": (
                AnnotationEdit,
                AnnotationView,
            ),
        }
    )
    models = {model for pair in catalog.values() for model in pair if model is not None}
    refs, definitions = models_json_schema(
        [(model, "validation") for model in sorted(models, key=lambda model: model.__name__)]
    )
    endpoints = {
        endpoint: {
            "request": refs[(request, "validation")] if request else None,
            "response": refs[(response, "validation")],
        }
        for endpoint, (request, response) in catalog.items()
    }
    print(
        json.dumps(
            {
                "schema_version": 1,
                "api_version": "v1",
                "catalog_only": True,
                "implemented": [
                    "POST /v1/student/assessments/upload",
                    "GET /v1/student/assessments/{id}/status",
                    "POST /v1/admin/knowledge/upload",
                    "GET /v1/admin/knowledge/{id}/status",
                    *[endpoint for endpoint in catalog if "/studio/" in endpoint],
                ],
                "endpoints": endpoints,
                **definitions,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
