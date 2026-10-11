import asyncio
import os

import httpx
import pytest

from app.model_gateway.gateway import LiteLLMModelGateway
from app.model_gateway.registry import Alias, load_registry
from app.model_gateway.types import GatewayError, ImageInput
from tests.test_model_gateway import MESSAGES, TOOLS, Answer, index

pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_MODEL_INTEGRATION") != "1",
    reason="Requires isolated synthetic provider proxies",
)


@pytest.mark.parametrize(
    "host,model",
    [
        ("model-openai", "openai/gpt-4o-mini-2024-07-18"),
        ("model-deepseek", "deepseek/deepseek-v4-pro"),
    ],
)
def test_pinned_proxy_provider_substitution(host: str, model: str) -> None:
    async def exercise() -> None:
        registry = load_registry()
        async with httpx.AsyncClient(
            base_url=f"http://{host}:4000/v1/",
            timeout=30,
            headers={"Authorization": "Bearer sk-synthetic-contract-proxy"},
            trust_env=False,
        ) as client:
            selected = registry.resolve({"TUTOR_MODEL": model})
            gw = LiteLLMModelGateway(client, registry, selected, "runtime")
            result = await gw.generate(Alias.TUTOR, MESSAGES)
            assert result.text == "Synthetic provider " + model.split("/", 1)[1] + ": 4"
            assert result.trace.provider_model == model
            structured = await gw.generate_structured(
                Alias.TUTOR,
                MESSAGES,
                Answer,
                mode="validated_json" if host == "model-deepseek" else "json_schema",
            )
            assert structured.value.answer == 4
            tools = await gw.call_tools(Alias.TUTOR, MESSAGES, TOOLS)
            assert tools.calls[0].arguments.model_dump() == {"expression": "2+2"}
            image = ImageInput(media_type="image/png", data=b"\x89PNG\r\n\x1a\nsynthetic")
            if host == "model-deepseek":
                with pytest.raises(GatewayError, match="unsupported_vision"):
                    await gw.analyze_images(Alias.TUTOR, MESSAGES, [image])
            vision = await gw.analyze_images(Alias.VISION, MESSAGES, [image])
            assert vision.trace.provider_model.startswith("openai/")
            assert vision.text == "Synthetic provider gpt-4o-2024-08-06: 4"
            embeddings = await gw.embed(["synthetic math"], index())
            assert embeddings.records[0].dimensions == 1536
            assert embeddings.records[0].index_release == "synthetic-index-1"

    asyncio.run(exercise())
