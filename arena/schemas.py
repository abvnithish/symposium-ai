from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


class Stance(str, Enum):
    support = "support"
    oppose = "oppose"
    neutral = "neutral"
    no_opinion = "no_opinion"


class RequestType(str, Enum):
    read_artifact = "READ_ARTIFACT"
    read_source = "READ_SOURCE"


class ModelRequest(BaseModel):
    type: RequestType
    path: str | None = None
    reason: str | None = None


class AgentTurn(BaseModel):
    stance: Stance = Stance.neutral
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    reasoning: str = ""
    proposal: str = ""
    critiques: list[str] = Field(default_factory=list)
    topic_suggestions: list[str] = Field(default_factory=list)
    requests: list[ModelRequest] = Field(default_factory=list)
    no_opinion: bool = False

    @staticmethod
    def fallback(error: str) -> "AgentTurn":
        return AgentTurn(
            stance=Stance.no_opinion,
            confidence=0.0,
            reasoning=f"Failed to produce valid JSON: {error}",
            proposal="",
            critiques=[],
            topic_suggestions=[],
            requests=[],
            no_opinion=True,
        )


class TopicCreate(BaseModel):
    title: str
    priority: int = 0


class TopicPriorityUpdate(BaseModel):
    topic_id: str
    priority: int


class TopicDecisionType(str, Enum):
    resolve = "RESOLVE"
    deadlock = "DEADLOCK"
    skip = "SKIP"


class TopicDecision(BaseModel):
    type: TopicDecisionType
    topic_id: str
    conclusion: str | None = None


class ArbiterTurn(BaseModel):
    selected_topic_id: str | None = None
    create_topics: list[TopicCreate] = Field(default_factory=list)
    priority_updates: list[TopicPriorityUpdate] = Field(default_factory=list)
    decisions: list[TopicDecision] = Field(default_factory=list)
    open_items: list[str] = Field(default_factory=list)
    cannot_resolve: bool = False
    reason: str = ""
    final_answer: str = ""
    requests: list[ModelRequest] = Field(default_factory=list)

    @staticmethod
    def fallback(error: str) -> "ArbiterTurn":
        return ArbiterTurn(
            selected_topic_id=None,
            cannot_resolve=True,
            reason=f"Failed to produce valid JSON: {error}",
            final_answer="",
            open_items=[f"Arbiter JSON parse failure: {error}"],
        )


class TranscriptEvent(BaseModel):
    ts: str
    type: str
    data: dict[str, Any] = Field(default_factory=dict)

