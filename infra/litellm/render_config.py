"""The API and pinned proxy resolve exactly the same checked-in model registry."""

import json
import os
import sys
from pathlib import Path

from app.model_gateway.registry import load_registry


def render() -> dict[str, object]:
    registry = load_registry()
    models = registry.resolve(os.environ)
    fixture = os.environ.get("MODEL_TEST_TRANSPORT") == "1"
    if fixture and os.environ.get("APP_ENV") != "test":
        raise ValueError("fixture transport requires test environment")
    deployments = []
    for alias, model in models.items():
        caps = registry.models[model]
        params: dict[str, object] = {"model": model, "api_key": "os.environ/" + caps.key_env}
        if caps.provider == "deepseek":
            params["thinking"] = {"type": "disabled"}
        if fixture:
            params["api_base"] = "http://model-fixture:8000/v1"
        deployments.append({"model_name": alias.value, "litellm_params": params})
    return {
        "model_list": deployments,
        "general_settings": {"master_key": "os.environ/LITELLM_MASTER_KEY"},
        "litellm_settings": {
            "set_verbose": False,
            "drop_params": False,
            "turn_off_message_logging": True,
            "num_retries": 0,
        },
        "router_settings": {"num_retries": 0, "disable_cooldowns": True},
    }


if __name__ == "__main__":
    config = render()
    if "--print" in sys.argv:
        print(json.dumps(config, indent=2))
    else:
        path = Path("/tmp/tutorbot-proxy.json")
        path.write_text(json.dumps(config))
        os.execvp("litellm", ["litellm", "--config", str(path), "--port", "4000"])
