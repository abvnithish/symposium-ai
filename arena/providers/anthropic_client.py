from __future__ import annotations

from anthropic import Anthropic

from arena.providers.base import LLMClient, LLMResponse
from arena.types import Message, ModelSpec


class AnthropicClient(LLMClient):
    def __init__(self, spec: ModelSpec, *, api_key: str):
        super().__init__(spec)
        self._client = Anthropic(api_key=api_key)

    def complete(self, messages: list[Message], *, max_output_tokens: int = 600) -> LLMResponse:
        system_parts = [m.content for m in messages if m.role == "system"]
        system = "\n\n".join(system_parts).strip() if system_parts else None

        anthro_messages: list[dict] = []
        for m in messages:
            if m.role == "system":
                continue
            if m.role == "assistant":
                anthro_messages.append({"role": "assistant", "content": m.content})
            else:
                anthro_messages.append({"role": "user", "content": m.content})

        resp = self._client.messages.create(
            model=self.spec.model,
            max_tokens=max_output_tokens,
            system=system,
            messages=anthro_messages,
        )
        text_chunks: list[str] = []
        for block in resp.content:
            if getattr(block, "type", None) == "text":
                text_chunks.append(block.text)
        text = ("\n".join(text_chunks)).strip()
        return LLMResponse(text=text, model=self.spec.model, provider="claude")

