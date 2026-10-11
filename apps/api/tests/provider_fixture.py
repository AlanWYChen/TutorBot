"""Synthetic provider HTTP server for pinned LiteLLM contract tests only."""

import os

from fastapi import FastAPI, HTTPException, Request

if os.environ.get("APP_ENV") != "test":
    raise RuntimeError("synthetic provider requires test mode")

app = FastAPI()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/chat/completions")
async def chat(request: Request) -> dict[str, object]:
    payload = await request.json()
    expected_key = (
        "synthetic-deepseek-key"
        if payload["model"].startswith("deepseek")
        else "synthetic-openai-key"
    )
    if request.headers.get("Authorization") != "Bearer " + expected_key:
        raise HTTPException(401, "synthetic provider credential mismatch")
    message: dict[str, object] = {
        "role": "assistant",
        "content": "Synthetic provider " + payload["model"] + ": 4",
    }
    finish = "stop"
    if payload.get("tools"):
        name = payload["tools"][0]["function"]["name"]
        message.update(
            content=None,
            tool_calls=[
                {
                    "id": "synthetic-call-1",
                    "type": "function",
                    "function": {"name": name, "arguments": '{"expression":"2+2"}'},
                }
            ],
        )
        finish = "tool_calls"
    elif payload.get("response_format"):
        message["content"] = '{"answer":4}'
    return {
        "id": "synthetic-chat-1",
        "object": "chat.completion",
        "created": 1,
        "model": payload["model"],
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    }


@app.post("/v1/embeddings")
async def embeddings(request: Request) -> dict[str, object]:
    payload = await request.json()
    return {
        "object": "list",
        "model": payload["model"],
        "data": [
            {
                "object": "embedding",
                "index": i,
                "embedding": [0.01] * payload.get("dimensions", 1536),
            }
            for i, _ in enumerate(payload["input"])
        ],
        "usage": {"prompt_tokens": 2, "total_tokens": 2},
    }
