import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

import httpx

from app.config import Settings
from app.model_gateway.gateway import LiteLLMModelGateway, ModelGateway
from app.model_gateway.registry import load_registry
from app.model_gateway.types import GatewayError


@asynccontextmanager
async def model_gateway(settings: Settings) -> AsyncIterator[ModelGateway]:
    url = urlsplit(settings.litellm_base_url)
    if (
        url.scheme not in {"http", "https"}
        or url.username
        or url.password
        or url.query
        or url.fragment
    ):
        raise GatewayError("invalid_proxy_url")
    if settings.app_env == "production" and url.scheme != "https":
        raise GatewayError("production_proxy_requires_tls")
    key = settings.litellm_master_key.get_secret_value()
    if not key or key == "not-configured":
        raise GatewayError("proxy_key_missing")
    registry = load_registry()
    async with httpx.AsyncClient(
        base_url=settings.litellm_base_url.rstrip("/") + "/",
        headers={"Authorization": "Bearer " + key},
        timeout=httpx.Timeout(60, connect=5),
        follow_redirects=False,
        trust_env=False,
    ) as client:
        yield LiteLLMModelGateway(
            client, registry, registry.resolve(os.environ), settings.service_mode
        )
