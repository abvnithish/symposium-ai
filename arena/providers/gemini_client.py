from __future__ import annotations
from pydantic import BaseModel

from google import genai
from google.genai import types

from arena.providers.base import LLMClient, LLMResponse
from arena.types import Message, ModelSpec


class GeminiClient(LLMClient):
    def __init__(
        self, 
        spec: ModelSpec, 
        *, 
        api_key: str, 
        google_cloud_project: str | None = None,
        google_cloud_location: str = "us-central1"
    ):
        super().__init__(spec)
        self.api_key = api_key
        self.project = google_cloud_project
        self.location = google_cloud_location
        
        # Primary client (Vertex AI if project is provided)
        self._vertex_client = None
        if self.project:
            try:
                self._vertex_client = genai.Client(
                    vertexai=True,
                    project=self.project,
                    location=self.location
                )
            except Exception as e:
                print(f"Warning: Failed to initialize Vertex AI client: {e}")

        # Fallback client (AI Studio / API Key)
        self._api_key_client = genai.Client(api_key=self.api_key)

    def complete(
        self,
        messages: list[Message],
        *,
        max_output_tokens: int = 600,
        response_model: type[BaseModel] | None = None,
    ) -> LLMResponse:
        # Prepare contents
        user_contents = []
        system_instructions = None
        for m in messages:
            if m.role == "system":
                system_instructions = m.content
            else:
                role = "user" if m.role == "user" else "model"
                user_contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m.content)]))

        config_dict = {"max_output_tokens": max_output_tokens}
        if response_model:
            config_dict["response_mime_type"] = "application/json"
            config_dict["response_schema"] = response_model

        # Attempt Vertex AI first if available
        if self._vertex_client:
            try:
                resp = self._vertex_client.models.generate_content(
                    model=self.spec.model,
                    contents=user_contents,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instructions,
                        **config_dict
                    ),
                )
                text = (getattr(resp, "text", None) or "").strip()
                return LLMResponse(text=text, model=self.spec.model, provider="gemini-vertex")
            except Exception as e:
                print(f"Warning: Vertex AI call failed, falling back to AI Studio. Error: {e}")

        # Fallback to AI Studio
        resp = self._api_key_client.models.generate_content(
            model=self.spec.model,
            contents=user_contents,
            config=types.GenerateContentConfig(
                system_instruction=system_instructions,
                **config_dict
            ),
        )
        text = (getattr(resp, "text", None) or "").strip()
        return LLMResponse(text=text, model=self.spec.model, provider="gemini-studio")

