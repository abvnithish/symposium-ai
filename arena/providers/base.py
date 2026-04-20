from __future__ import annotations
from dataclasses import dataclass
from pydantic import BaseModel

from arena.types import Message, ModelSpec


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    provider: str


class LLMClient:
    def __init__(self, spec: ModelSpec):
        self.spec = spec

    def complete(
        self,
        messages: list[Message],
        *,
        max_output_tokens: int = 600,
        response_model: type[BaseModel] | None = None,
    ) -> LLMResponse:
        raise NotImplementedError

