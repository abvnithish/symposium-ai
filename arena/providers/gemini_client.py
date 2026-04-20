from __future__ import annotations
from pydantic import BaseModel

from google import genai
from google.genai import types

from arena.providers.base import LLMClient, LLMResponse
from arena.types import Message, ModelSpec


class GeminiClient(LLMClient):
    def __init__(self, spec: ModelSpec, *, api_key: str):
        super().__init__(spec)
        self._client = genai.Client(api_key=api_key)

    def complete(
        self,
        messages: list[Message],
        *,
        max_output_tokens: int = 600,
        response_model: type[BaseModel] | None = None,
    ) -> LLMResponse:
        # Convert messages to Gemini SDK contents
        contents: list[types.Content] = []
        for m in messages:
            role = "user" if m.role == "user" else "model"
            # In Gemini, system prompt can be handled separately in config, 
            # but for consistency with base, we treat it as a message or use system_instruction.
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m.content)]))

        # Check for system message to use as system_instruction
        system_instructions = None
        user_contents = []
        for c in contents:
            if messages[contents.index(c)].role == "system":
                system_instructions = c.parts[0].text
            else:
                user_contents.append(c)

        config_dict = {"max_output_tokens": max_output_tokens}
        if response_model:
            config_dict["response_mime_type"] = "application/json"
            config_dict["response_schema"] = response_model

        resp = self._client.models.generate_content(
            model=self.spec.model,
            contents=user_contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instructions,
                **config_dict
            ),
        )
        
        # If response_model was used, SDK might return parsed object, 
        # but we currently expect LLMResponse to carry the raw text.
        text = (getattr(resp, "text", None) or "").strip()
        return LLMResponse(text=text, model=self.spec.model, provider="gemini")

