import base64
from dataclasses import dataclass
from typing import Annotated, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator

from app.model_gateway.registry import Alias

T = TypeVar("T", bound=BaseModel)


class GatewayError(Exception):
    """Only stable codes cross this boundary; never provider payloads or prompts."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(code)


class SafeModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Message(SafeModel):
    role: Literal["system", "user", "assistant"]
    content: Annotated[str, Field(min_length=1, max_length=20000)] = Field(repr=False)


class ImageInput(SafeModel):
    media_type: Literal["image/png", "image/jpeg"]
    data: Annotated[bytes, Field(min_length=8, max_length=4 * 1024 * 1024)] = Field(repr=False)

    @model_validator(mode="after")
    def signature(self) -> "ImageInput":
        prefix = b"\x89PNG\r\n\x1a\n" if self.media_type == "image/png" else b"\xff\xd8\xff"
        if not self.data.startswith(prefix):
            raise ValueError("image signature mismatch")
        return self

    def data_url(self) -> str:
        return "data:" + self.media_type + ";base64," + base64.b64encode(self.data).decode()


class Usage(SafeModel):
    prompt_tokens: int = Field(ge=0, strict=True)
    completion_tokens: int = Field(ge=0, strict=True)
    total_tokens: int = Field(ge=0, strict=True)


class Trace(SafeModel):
    requested_alias: Alias
    selected_alias: Alias
    provider_model: str
    fallback_reason: str | None = None
    structured_mode: Literal["json_schema", "validated_json"] | None = None
    registry_version: Literal[1] = 1


class Generation(SafeModel):
    text: str = Field(min_length=1, max_length=100000, repr=False)
    trace: Trace
    usage: Usage


class StructuredGeneration(SafeModel, Generic[T]):
    value: T = Field(repr=False)
    trace: Trace
    usage: Usage


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments: type[BaseModel]


class ToolProposal(SafeModel):
    call_id: str = Field(min_length=1, max_length=128)
    name: str = Field(pattern=r"^[a-zA-Z_][a-zA-Z0-9_]{0,63}$")
    arguments: SerializeAsAny[BaseModel] = Field(repr=False)


class ToolGeneration(SafeModel):
    calls: list[ToolProposal] = Field(min_length=1, max_length=16)
    trace: Trace
    usage: Usage


class EmbeddingIndex(SafeModel):
    model_id: str = Field(min_length=1, max_length=200)
    dimensions: int = Field(gt=0, le=65536)
    chunker_version: str = Field(min_length=1, max_length=128)
    index_release: str = Field(min_length=1, max_length=128)


class EmbeddingRecord(SafeModel):
    vector: list[Annotated[float, Field(allow_inf_nan=False)]] = Field(repr=False)
    model_id: str
    dimensions: int
    chunker_version: str
    content_hash: str
    index_release: str


class EmbeddingBatch(SafeModel):
    records: list[EmbeddingRecord]
    trace: Trace
