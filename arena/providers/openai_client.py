from __future__ import annotations
from pydantic import BaseModel

from openai import OpenAI

from arena.providers.base import LLMClient, LLMResponse
from arena.types import Message, ModelSpec


class OpenAIClient(LLMClient):
    def __init__(self, spec: ModelSpec, *, api_key: str):
        super().__init__(spec)
        self._client = OpenAI(api_key=api_key)

    def complete(
        self,
        messages: list[Message],
        *,
        max_output_tokens: int = 600,
        response_model: type[BaseModel] | None = None,
    ) -> LLMResponse:
        chat_messages: list[dict] = [{"role": m.role, "content": m.content} for m in messages]
        
        config: dict = {
            "model": self.spec.model,
            "messages": chat_messages,
            "max_completion_tokens": max_output_tokens,
        }
        
        if response_model:
            config["response_format"] = {"type": "json_object"}
            # OpenAI's JSON mode requires the prompt to contain the word "JSON"
            if not any("json" in m["content"].lower() for m in chat_messages):
                chat_messages[-1]["content"] += "\nReturn strict JSON only."

        resp = self._client.chat.completions.create(**config)
        text = (resp.choices[0].message.content or "").strip()
        return LLMResponse(text=text, model=self.spec.model, provider="gpt")

