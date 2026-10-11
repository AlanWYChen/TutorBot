"""Export future /v1 contracts without mounting placeholder API routes."""

import json

from pydantic.json_schema import models_json_schema

from app.domain.contracts import ENDPOINT_CONTRACTS


def main() -> None:
    models = {model for pair in ENDPOINT_CONTRACTS.values() for model in pair if model is not None}
    refs, definitions = models_json_schema(
        [(model, "validation") for model in sorted(models, key=lambda model: model.__name__)]
    )
    endpoints = {
        endpoint: {
            "request": refs[(request, "validation")] if request else None,
            "response": refs[(response, "validation")],
        }
        for endpoint, (request, response) in ENDPOINT_CONTRACTS.items()
    }
    print(
        json.dumps(
            {
                "schema_version": 1,
                "api_version": "v1",
                "mounted": False,
                "endpoints": endpoints,
                **definitions,
            },
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
