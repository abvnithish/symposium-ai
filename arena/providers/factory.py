from __future__ import annotations

import time
from tenacity import retry, wait_exponential_jitter, stop_after_attempt

from arena.providers.base import LLMClient
from arena.settings import Settings
from arena.types import ModelSpec, ProviderName

def _wrap_with_retry_and_delay(client: LLMClient) -> LLMClient:
    original_complete = client.complete

    @retry(
        wait=wait_exponential_jitter(initial=5, max=60),
        stop=stop_after_attempt(5),
        reraise=True
    )
    def resilient_complete(*args, **kwargs):
        # Space out the calls to help avoid rapid burst rate limits
        time.sleep(3)
        return original_complete(*args, **kwargs)

    client.complete = resilient_complete
    return client

def build_client(spec: ModelSpec, settings: Settings) -> LLMClient:
    provider: ProviderName = spec.provider
    if provider == "gpt":
        if not settings.openai_api_key:
            raise RuntimeError("Missing OPENAI_API_KEY")
        from arena.providers.openai_client import OpenAIClient

        return _wrap_with_retry_and_delay(OpenAIClient(spec, api_key=settings.openai_api_key))
    if provider == "claude":
        if not settings.anthropic_api_key:
            raise RuntimeError("Missing ANTHROPIC_API_KEY")
        from arena.providers.anthropic_client import AnthropicClient

        return _wrap_with_retry_and_delay(AnthropicClient(spec, api_key=settings.anthropic_api_key))
    if provider == "gemini":
        if not settings.google_api_key:
            raise RuntimeError("Missing GOOGLE_API_KEY")
        from arena.providers.gemini_client import GeminiClient

        return _wrap_with_retry_and_delay(GeminiClient(spec, api_key=settings.google_api_key))
    raise RuntimeError(f"Unknown provider: {provider}")

