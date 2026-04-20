from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class TopicStatus(str, Enum):
    open = "open"
    resolved = "resolved"
    deadlocked = "deadlocked"
    skipped = "skipped"


@dataclass
class Topic:
    topic_id: str
    title: str
    priority: int = 0
    status: TopicStatus = TopicStatus.open
    followups_used: int = 0
    max_followups: int = 3
    conclusion: str = ""
    history: list[str] = field(default_factory=list)


class TopicState:
    def __init__(self, *, default_max_followups: int = 3):
        self.default_max_followups = default_max_followups
        self.topics: dict[str, Topic] = {}
        self._next_id = 1

    def create(self, title: str, *, priority: int = 0, max_followups: int | None = None) -> Topic:
        tid = f"t{self._next_id}"
        self._next_id += 1
        t = Topic(
            topic_id=tid,
            title=title.strip(),
            priority=int(priority),
            max_followups=int(max_followups or self.default_max_followups),
        )
        self.topics[tid] = t
        return t

    def get(self, topic_id: str) -> Topic | None:
        return self.topics.get(topic_id)

    def open_topics(self) -> list[Topic]:
        return [t for t in self.topics.values() if t.status == TopicStatus.open]

    def apply_priority_update(self, topic_id: str, priority: int) -> None:
        t = self.topics.get(topic_id)
        if not t:
            return
        t.priority = int(priority)

    def mark_resolved(self, topic_id: str, conclusion: str | None = None) -> None:
        t = self.topics.get(topic_id)
        if not t:
            return
        t.status = TopicStatus.resolved
        if conclusion:
            t.conclusion = conclusion.strip()

    def mark_deadlocked(self, topic_id: str, reason: str | None = None) -> None:
        t = self.topics.get(topic_id)
        if not t:
            return
        t.status = TopicStatus.deadlocked
        if reason:
            t.history.append(f"DEADLOCK: {reason.strip()}")

    def mark_skipped(self, topic_id: str, reason: str | None = None) -> None:
        t = self.topics.get(topic_id)
        if not t:
            return
        t.status = TopicStatus.skipped
        if reason:
            t.history.append(f"SKIP: {reason.strip()}")

    def note(self, topic_id: str, note: str) -> None:
        t = self.topics.get(topic_id)
        if not t:
            return
        t.history.append(note.strip())

    def bump_followup(self, topic_id: str) -> None:
        t = self.topics.get(topic_id)
        if not t:
            return
        if t.status != TopicStatus.open:
            return
        t.followups_used += 1
        if t.followups_used > t.max_followups:
            t.status = TopicStatus.deadlocked

    def select_fallback(self, *, avoid_topic_id: str | None = None) -> str | None:
        candidates = [
            t
            for t in self.topics.values()
            if t.status == TopicStatus.open and t.topic_id != avoid_topic_id
        ]
        if not candidates:
            candidates = [t for t in self.topics.values() if t.status == TopicStatus.open]
        if not candidates:
            return None
        candidates.sort(key=lambda t: (t.priority, -t.followups_used), reverse=True)
        return candidates[0].topic_id

    def all_done(self) -> bool:
        if not self.topics:
            return True
        return all(t.status != TopicStatus.open for t in self.topics.values())

