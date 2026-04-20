from __future__ import annotations

import json
from pathlib import Path

import typer
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from arena.arena import ArenaConfig, ArenaAgent, normalize_provider, run_arena
from arena.providers.factory import build_client
from arena.settings import get_settings
from arena.types import Message, ModelSpec

app = typer.Typer(add_completion=False, help="Multi-LLM debate arena (Gemini + Claude + GPT).")
console = Console()


def _read_text_file(p: Path) -> str:
    if not p.exists():
        raise typer.BadParameter(f"File not found: {p}")
    if p.is_dir():
        raise typer.BadParameter(f"Expected a file but got directory: {p}")
    return p.read_text(encoding="utf-8", errors="replace").strip()


def _parse_agent_spec(spec: str) -> ArenaAgent:
    """
    Format: provider:model:name
      - provider: gpt|claude|gemini
      - model: provider model string
      - name: unique agent name (allows duplicates across provider/model)
    Example: gemini:gemini-2.5-pro:geminiA
    """
    parts = spec.split(":", 2)
    if len(parts) != 3:
        raise typer.BadParameter("Agent spec must be provider:model:name")
    provider_raw, model, name = parts
    provider = normalize_provider(provider_raw)
    if not model.strip() or not name.strip():
        raise typer.BadParameter("Agent spec must include non-empty model and name")
    return ArenaAgent(
        name=name.strip(),
        spec=ModelSpec(provider=provider, model=model.strip()),
        system_prompt=(
            "You are an agent in a debate arena.\n"
            "Be reasonable but very critical, logical, and unbiased.\n"
            "Be open to updating your view based on others’ evidence.\n"
            "If you have no opinion, say so.\n"
            "Follow the output format exactly as requested."
        ),
    )


@app.command()
def ping(
    provider: str = typer.Option(..., help="gpt | claude | gemini"),
    model: str | None = typer.Option(None, help="Override model name for provider"),
):
    """Sanity-check that a provider key + model works."""
    load_dotenv()
    settings = get_settings()
    p = normalize_provider(provider)

    default_model = {
        "gpt": settings.openai_model,
        "claude": settings.anthropic_model,
        "gemini": settings.gemini_model,
    }[p]
    spec = ModelSpec(provider=p, model=model or default_model)
    client = build_client(spec, settings)

    resp = client.complete(
        [
            Message(role="system", content="You are a quick connectivity test."),
            Message(role="user", content="Reply with exactly: pong"),
        ],
        max_output_tokens=20,
    )
    console.print(Panel.fit(resp.text, title=f"{p} / {spec.model}"))


@app.command()
def run(
    question: str | None = typer.Argument(
        None, help="The question to debate (omit if using --question-file)"
    ),
    question_file: Path | None = typer.Option(
        None, help="Path to a .txt file containing the question"
    ),
    context_file: list[Path] = typer.Option(
        default_factory=list,
        help="Optional .txt file(s) with extra context to include (repeatable)",
    ),
    artifact: list[Path] = typer.Option(
        default_factory=list, help="Artifact file path(s) to review (repeatable)"
    ),
    agent: list[str] = typer.Option(
        default_factory=list,
        help="Repeatable agent spec: provider:model:name (e.g., gemini:gemini-2.5-pro:geminiA)",
    ),
    arbiter: str | None = typer.Option(
        None,
        help="Arbiter spec: provider[:model] (defaults from env). Example: gpt or gpt:gpt-4.1-mini",
    ),
    max_steps: int = typer.Option(18, help="Global max steps (safety guard)"),
    topic_max_followups: int = typer.Option(3, help="Max follow-ups per sub-topic before deadlock"),
    out: Path | None = typer.Option(None, help="Write transcript JSON to this path"),
    max_output_tokens: int = typer.Option(700, help="Max output tokens for model responses"),
    show_transcript: bool = typer.Option(False, help="Print full transcript"),
):
    """Run a topic-driven debate to improve an artifact and answer a question."""
    load_dotenv()
    settings = get_settings()

    if question_file:
        question = _read_text_file(question_file)
    if not question or not question.strip():
        raise typer.BadParameter("Provide a question argument or --question-file.")

    extra_context = ""
    if context_file:
        blocks = [f"[{p}]\n{_read_text_file(p)}" for p in context_file]
        extra_context = "\n\n".join(blocks).strip()

    if not artifact:
        raise typer.BadParameter("At least one --artifact path is required for topic-driven mode.")

    if not agent:
        # Sensible default: gemini + gpt + claude (unique names)
        agent = [
            f"gemini:{settings.gemini_model}:geminiA",
            f"gpt:{settings.openai_model}:gpt",
            f"claude:{settings.anthropic_model}:claude",
        ]

    agents_list = [_parse_agent_spec(a) for a in agent]
    names = [a.name for a in agents_list]
    if len(names) != len(set(names)):
        raise typer.BadParameter("Agent names must be unique (use distinct :name suffixes).")

    if arbiter:
        arb_parts = arbiter.split(":", 1)
        arb_provider = normalize_provider(arb_parts[0])
        arb_model = (
            arb_parts[1]
            if len(arb_parts) == 2
            else {
                "gpt": settings.openai_model,
                "claude": settings.anthropic_model,
                "gemini": settings.gemini_model,
            }[arb_provider]
        )
    else:
        arb_provider = normalize_provider(settings.arena_arbiter_provider)
        arb_model = {
            "gpt": settings.openai_model,
            "claude": settings.anthropic_model,
            "gemini": settings.gemini_model,
        }[arb_provider]

    cfg = ArenaConfig(
        question=question,
        context=extra_context,
        agents=agents_list,
        arbiter=ModelSpec(provider=arb_provider, model=arb_model),
        max_steps=max_steps,
        artifact_paths=[str(p) for p in artifact],
        max_output_tokens=max_output_tokens,
        topic_max_followups=topic_max_followups,
    )

    res = run_arena(cfg, settings)

    console.print(
        Panel.fit(
            res.final_answer,
            title=("AGREED" if res.agreed else "SYNTHESIZED") + f" (steps={res.steps_ran})",
        )
    )

    if show_transcript:
        for t in res.transcript:
            console.print(Panel(json.dumps(t.model_dump(), indent=2), title=f"{t.ts}  {t.type}"))

    if out:
        payload = res.to_json()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        console.print(f"Wrote transcript to {out}")


def main() -> None:
    app()


if __name__ == "__main__":
    main()

