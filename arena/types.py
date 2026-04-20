from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ProviderName = Literal["gpt", "claude", "gemini"]


@dataclass(frozen=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True)
class ModelSpec:
    provider: ProviderName
    model: str

