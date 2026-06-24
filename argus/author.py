"""Provider-agnostic LLM brief authoring helpers."""
from __future__ import annotations

from typing import Any

SYSTEM_PROMPT = """You write Phase 1 Argus research briefs.
Rules:
- Do not emit numeric scores, rankings, or trade instructions.
- Use only the supplied point-in-time snapshot.
- Include a falsifiable invalidation_condition.
- Return thesis and invalidation_condition fields.
"""


def draft_prompt(ticker: str, snapshot: dict[str, Any]) -> str:
    return f"Ticker: {ticker}\nSnapshot: {snapshot}\nWrite a concise falsifiable thesis."


def validate_brief_payload(payload: dict[str, str]) -> dict[str, str]:
    thesis = payload.get("thesis", "").strip()
    invalidation = payload.get("invalidation_condition", "").strip()
    if not thesis:
        raise ValueError("thesis is required")
    if not invalidation:
        raise ValueError("invalidation_condition is required")
    banned = ("score", "ranking", "buy", "sell", "strong buy")
    text = f"{thesis} {invalidation}".lower()
    if any(word in text for word in banned):
        raise ValueError("brief contains scoring/ranking/trading language")
    return {"thesis": thesis, "invalidation_condition": invalidation}


def example_claude_call(client: Any, ticker: str, snapshot: dict[str, Any]) -> dict[str, str]:
    message = client.messages.create(
        model="claude-3-5-sonnet-latest",
        max_tokens=400,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": draft_prompt(ticker, snapshot)}],
    )
    return validate_brief_payload(message.content[0].input)
