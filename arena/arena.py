from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from arena.artifact import ArtifactStore, workspace_root
from arena.json_utils import repair_json
from arena.prompts import arbiter_system_prompt, agent_system_prompt
from arena.providers.factory import build_client
from arena.schemas import AgentTurn, ArbiterTurn, RequestType, TranscriptEvent
from arena.settings import Settings
from arena.topics import TopicState, TopicStatus
from arena.types import Message, ModelSpec, ProviderName


@dataclass(frozen=True)
class ArenaAgent:
    name: str
    spec: ModelSpec
    system_prompt: str


@dataclass(frozen=True)
class ArenaConfig:
    question: str
    context: str
    agents: list[ArenaAgent]
    arbiter: ModelSpec
    artifact_paths: list[str]
    max_output_tokens: int = 700
    max_steps: int = 18
    topic_max_followups: int = 3


@dataclass
class ArenaResult:
    agreed: bool
    final_answer: str
    steps_ran: int
    open_items: list[str]
    topics: dict[str, Any]
    transcript: list[TranscriptEvent]

    def to_json(self) -> dict[str, Any]:
        return {
            "agreed": self.agreed,
            "steps_ran": self.steps_ran,
            "final_answer": self.final_answer,
            "open_items": list(self.open_items),
            "topics": self.topics,
            "transcript": [e.model_dump() for e in self.transcript],
        }


def _now_iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


def _event(ev_type: str, **data: Any) -> TranscriptEvent:
    return TranscriptEvent(ts=_now_iso(), type=ev_type, data=data)


def _format_revealed_content(revealed: dict[str, str]) -> str:
    if not revealed:
        return ""
    lines = ["REVEALED_ARTIFACT_CONTENT:"]
    for path, content in revealed.items():
        lines.append(f"--- FILE: {path} ---")
        lines.append(content)
        lines.append("--- END FILE ---")
    return "\n".join(lines)


def _safe_parse_agent(text: str) -> AgentTurn:
    repaired = repair_json(text)
    try:
        return AgentTurn.model_validate_json(repaired)
    except Exception as e:
        return AgentTurn.fallback(str(e))


def _safe_parse_arbiter(text: str) -> ArbiterTurn:
    repaired = repair_json(text)
    try:
        return ArbiterTurn.model_validate_json(repaired)
    except Exception as e:
        return ArbiterTurn.fallback(str(e))


def _format_topics_for_prompt(state: TopicState) -> str:
    if not state.topics:
        return "TOPICS: (none)"
    rows = []
    for t in state.topics.values():
        rows.append(
            f"- {t.topic_id} [{t.status}] prio={t.priority} followups={t.followups_used}/{t.max_followups}: {t.title}"
        )
    return "TOPICS:\n" + "\n".join(rows)


def _topic_to_json(t: Any) -> dict[str, Any]:
    # t is arena.topics.Topic, but keep it defensive.
    status = getattr(t, "status", None)
    status_val = getattr(status, "value", None) if status is not None else None
    return {
        "topic_id": getattr(t, "topic_id", ""),
        "title": getattr(t, "title", ""),
        "priority": int(getattr(t, "priority", 0)),
        "status": status_val or str(status),
        "followups_used": int(getattr(t, "followups_used", 0)),
        "max_followups": int(getattr(t, "max_followups", 0)),
        "conclusion": getattr(t, "conclusion", "") or "",
        "history": list(getattr(t, "history", []) or []),
    }


def run_arena(cfg: ArenaConfig, settings: Settings) -> ArenaResult:
    if len(cfg.agents) < 1:
        raise ValueError("ArenaConfig.agents must have at least 1 agent.")

    transcript: list[TranscriptEvent] = []
    open_items: list[str] = []
    revealed_content: dict[str, str] = {}  # Tracks content revealed via READ_ARTIFACT

    store = ArtifactStore(
        workspace_root=workspace_root(),
        artifact_paths=cfg.artifact_paths,
    )
    topic_state = TopicState(default_max_followups=cfg.topic_max_followups)

    agent_clients = {a.name: build_client(a.spec, settings) for a in cfg.agents}
    arbiter_client = build_client(cfg.arbiter, settings)

    transcript.append(_event("question", question=cfg.question))
    if cfg.context and cfg.context.strip():
        transcript.append(_event("context", text=cfg.context.strip()))
    transcript.append(_event("artifact_files", paths=store.artifact_paths))

    # ---- START: arbiter seeds topics ----
    seed_user = (
        f"Question:\n{cfg.question}\n\n"
        + (f"Context:\n{cfg.context}\n\n" if cfg.context and cfg.context.strip() else "")
        + f"{store.summarize_for_prompt()}\n\n"
        + _format_revealed_content(revealed_content) + "\n\n"
        + "Task:\n"
        + "- Propose an initial set of sub-topics to review (create_topics).\n"
        + "- Select the first topic to discuss (selected_topic_id) OR leave it null and create topics.\n"
        + "- If everything is perfect, you may set final_answer and leave topics empty.\n"
    )
    seed_resp = arbiter_client.complete(
        [Message(role="system", content=arbiter_system_prompt()), Message(role="user", content=seed_user)],
        max_output_tokens=cfg.max_output_tokens,
        response_model=ArbiterTurn,
    )
    seed_turn = _safe_parse_arbiter(seed_resp.text)
    transcript.append(_event("arbiter_seed_raw", text=seed_resp.text))
    transcript.append(_event("arbiter_seed", turn=seed_turn.model_dump()))

    # Arbiter might request to read artifact in seed
    for req in seed_turn.requests:
        if req.type == RequestType.read_artifact:
            for chunk in store.read_artifacts():
                revealed_content[chunk.path] = chunk.content
            transcript.append(_event("artifact_read", step=0, files=[p for p in revealed_content.keys()]))

    for tc in seed_turn.create_topics:
        t = topic_state.create(tc.title, priority=tc.priority, max_followups=cfg.topic_max_followups)
        transcript.append(_event("topic_created", topic_id=t.topic_id, title=t.title, priority=t.priority))

    if not topic_state.topics and not seed_turn.final_answer.strip():
        t = topic_state.create("Overall review", priority=1, max_followups=cfg.topic_max_followups)
        transcript.append(_event("topic_created", topic_id=t.topic_id, title=t.title, priority=t.priority))

    last_topic_id: str | None = None

    if seed_turn.final_answer.strip():
        return ArenaResult(
            agreed=True,
            final_answer=seed_turn.final_answer.strip(),
            steps_ran=0,
            open_items=seed_turn.open_items,
            topics={tid: _topic_to_json(t) for tid, t in topic_state.topics.items()},
            transcript=transcript,
        )

    current_topic_id = seed_turn.selected_topic_id or topic_state.select_fallback()

    # ---- CONTINUE: topic-driven steps ----
    steps = 0
    while steps < cfg.max_steps and current_topic_id is not None:
        steps += 1
        topic = topic_state.get(current_topic_id)
        if not topic or topic.status != TopicStatus.open:
            current_topic_id = topic_state.select_fallback(avoid_topic_id=last_topic_id)
            continue

        # deadlock guard: avoid selecting the same unresolved topic indefinitely
        if last_topic_id == current_topic_id and topic.followups_used >= topic.max_followups:
            topic_state.mark_deadlocked(current_topic_id, "Exceeded max follow-ups.")
            transcript.append(_event("topic_deadlocked", topic_id=current_topic_id, reason="Exceeded max follow-ups"))
            current_topic_id = topic_state.select_fallback(avoid_topic_id=current_topic_id)
            continue

        transcript.append(
            _event(
                "topic_selected",
                step=steps,
                topic_id=topic.topic_id,
                title=topic.title,
                followups_used=topic.followups_used,
                max_followups=topic.max_followups,
            )
        )

        # Agent responses (strict JSON)
        agent_turns: dict[str, AgentTurn] = {}
        for agent in cfg.agents:
            user_msg = (
                f"Question:\n{cfg.question}\n\n"
                + (f"Context:\n{cfg.context}\n\n" if cfg.context and cfg.context.strip() else "")
                + f"{store.summarize_for_prompt()}\n\n"
                + _format_revealed_content(revealed_content) + "\n\n"
                + f"{_format_topics_for_prompt(topic_state)}\n\n"
                + f"CURRENT_TOPIC: {topic.topic_id} — {topic.title}\n\n"
                + "Return strict JSON only.\n"
            )
            resp = agent_clients[agent.name].complete(
                [
                    Message(
                        role="system",
                        content=agent.system_prompt + "\n\n" + agent_system_prompt(agent_name=agent.name),
                    ),
                    Message(role="user", content=user_msg),
                ],
                max_output_tokens=cfg.max_output_tokens,
                response_model=AgentTurn,
            )
            parsed = _safe_parse_agent(resp.text)
            agent_turns[agent.name] = parsed
            transcript.append(_event("agent_raw", step=steps, agent=agent.name, text=resp.text))
            transcript.append(_event("agent_turn", step=steps, agent=agent.name, turn=parsed.model_dump()))

        # Arbiter decision (strict JSON)
        arb_user = (
            f"Question:\n{cfg.question}\n\n"
            + (f"Context:\n{cfg.context}\n\n" if cfg.context and cfg.context.strip() else "")
            + f"{store.summarize_for_prompt()}\n\n"
            + _format_revealed_content(revealed_content) + "\n\n"
            + f"{_format_topics_for_prompt(topic_state)}\n\n"
            + f"CURRENT_TOPIC: {topic.topic_id} — {topic.title}\n\n"
            + f"AGENT_OUTPUTS_JSON:\n{json.dumps({k: v.model_dump() for k, v in agent_turns.items()}, indent=2)}\n\n"
            + "Decide next actions:\n"
            + "- Select next topic (selected_topic_id)\n"
            + "Return strict JSON only.\n"
        )
        arb_resp = arbiter_client.complete(
            [Message(role="system", content=arbiter_system_prompt()), Message(role="user", content=arb_user)],
            max_output_tokens=cfg.max_output_tokens,
            response_model=ArbiterTurn,
        )
        arb_turn = _safe_parse_arbiter(arb_resp.text)
        transcript.append(_event("arbiter_raw", step=steps, text=arb_resp.text))
        transcript.append(_event("arbiter_turn", step=steps, turn=arb_turn.model_dump()))

        # Execute requests (re-read artifact/sources)
        for req in arb_turn.requests:
            if req.type == RequestType.read_artifact:
                for chunk in store.read_artifacts():
                    revealed_content[chunk.path] = chunk.content
                transcript.append(
                    _event(
                        "artifact_read",
                        step=steps,
                        files=[{"path": k, "truncated": False} for k in revealed_content.keys()],
                    )
                )
            elif req.type == RequestType.read_source and req.path:
                try:
                    chunk = store.read_path(req.path)
                    revealed_content[chunk.path] = chunk.content
                    transcript.append(_event("source_read", step=steps, path=chunk.path))
                except Exception as e:
                    transcript.append(_event("source_read_error", step=steps, path=req.path, error=str(e)))
                    open_items.append(f"Failed to read source {req.path}: {e}")

        # Apply new topics from arbiter + from agent suggestions (arbiter-controlled via create_topics)
        for tc in arb_turn.create_topics:
            t = topic_state.create(tc.title, priority=tc.priority, max_followups=cfg.topic_max_followups)
            transcript.append(_event("topic_created", step=steps, topic_id=t.topic_id, title=t.title, priority=t.priority))

        for pu in arb_turn.priority_updates:
            topic_state.apply_priority_update(pu.topic_id, pu.priority)
            transcript.append(_event("topic_priority_updated", step=steps, topic_id=pu.topic_id, priority=pu.priority))

        for decision in arb_turn.decisions:
            if decision.type.value == "RESOLVE":
                topic_state.mark_resolved(decision.topic_id, decision.conclusion)
                transcript.append(
                    _event(
                        "topic_resolved",
                        step=steps,
                        topic_id=decision.topic_id,
                        conclusion=decision.conclusion or "",
                    )
                )
            elif decision.type.value == "DEADLOCK":
                topic_state.mark_deadlocked(decision.topic_id, decision.conclusion or "Deadlocked.")
                transcript.append(
                    _event(
                        "topic_deadlocked",
                        step=steps,
                        topic_id=decision.topic_id,
                        reason=decision.conclusion or "Deadlocked.",
                    )
                )
            elif decision.type.value == "SKIP":
                topic_state.mark_skipped(decision.topic_id, decision.conclusion or "Skipped.")
                transcript.append(
                    _event(
                        "topic_skipped",
                        step=steps,
                        topic_id=decision.topic_id,
                        reason=decision.conclusion or "Skipped.",
                    )
                )

        # Open items accumulation
        if arb_turn.open_items:
            open_items.extend([x for x in arb_turn.open_items if x and x.strip()])
        if arb_turn.cannot_resolve:
            open_items.append(arb_turn.reason or "Arbiter could not resolve a conflict.")

        # Bump followup count for the topic we just discussed
        topic_state.bump_followup(current_topic_id)
        if topic_state.get(current_topic_id) and topic_state.get(current_topic_id).status == TopicStatus.deadlocked:
            transcript.append(
                _event(
                    "topic_deadlocked",
                    step=steps,
                    topic_id=current_topic_id,
                    reason="Exceeded max follow-ups.",
                )
            )

        # Stop if arbiter gives final answer
        if arb_turn.final_answer and arb_turn.final_answer.strip():
            return ArenaResult(
                agreed=not arb_turn.cannot_resolve,
                final_answer=arb_turn.final_answer.strip(),
                steps_ran=steps,
                open_items=open_items,
                topics={tid: _topic_to_json(t) for tid, t in topic_state.topics.items()},
                transcript=transcript,
            )

        last_topic_id = current_topic_id
        next_topic = arb_turn.selected_topic_id or topic_state.select_fallback(avoid_topic_id=last_topic_id)
        current_topic_id = next_topic

        if topic_state.all_done():
            break

    # ---- STOP: synthesis if max steps or no topics left ----
    synth_user = (
        f"Question:\n{cfg.question}\n\n"
        + (f"Context:\n{cfg.context}\n\n" if cfg.context and cfg.context.strip() else "")
        + f"{store.summarize_for_prompt()}\n\n"
        + f"{_format_topics_for_prompt(topic_state)}\n\n"
        + f"OPEN_ITEMS:\n{json.dumps(open_items[-20:], indent=2)}\n\n"
        + "Produce a best-effort final answer.\n"
        + "- If there are unresolved items, list them clearly.\n"
        + "- If the artifact is perfect, say so.\n"
        + "Return strict JSON only using the ArbiterTurn schema, with final_answer filled.\n"
    )
    synth_resp = arbiter_client.complete(
        [Message(role="system", content=arbiter_system_prompt()), Message(role="user", content=synth_user)],
        max_output_tokens=cfg.max_output_tokens,
        response_model=ArbiterTurn,
    )
    synth_turn = _safe_parse_arbiter(synth_resp.text)
    transcript.append(_event("arbiter_synth_raw", text=synth_resp.text))
    transcript.append(_event("arbiter_synth", turn=synth_turn.model_dump()))
    if synth_turn.open_items:
        open_items.extend([x for x in synth_turn.open_items if x and x.strip()])
    if synth_turn.cannot_resolve:
        open_items.append(synth_turn.reason or "Arbiter could not resolve a conflict.")

    return ArenaResult(
        agreed=False,
        final_answer=(synth_turn.final_answer or "").strip(),
        steps_ran=steps,
        open_items=open_items,
        topics={tid: _topic_to_json(t) for tid, t in topic_state.topics.items()},
        transcript=transcript,
    )


def normalize_provider(name: str) -> ProviderName:
    lowered = name.strip().lower()
    if lowered in ("gpt", "openai"):
        return "gpt"
    if lowered in ("claude", "anthropic"):
        return "claude"
    if lowered in ("gemini", "google"):
        return "gemini"
    raise ValueError(f"Unknown provider: {name}")

