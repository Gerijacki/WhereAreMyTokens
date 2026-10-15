"""Rule-based work categorization of prompts (turns).

Scores every category from the prompt text, the tools the turn used, the shell commands
it ran and a few derived signals, then keeps the best one. The per-category scores are
stored with the turn so the UI can explain the choice.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import yaml

RULES_FILE = Path(__file__).with_name("rules.yaml")
CONTINUATION = re.compile(
    r"^\s*(continue|continua|continúa|go on|segueix|sigue|next|seguent|següent|ok|okay|yes|si|sí|vale|dale|"
    r"endavant|adelante|proceed|do it|fes-ho|hazlo)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class Category:
    name: str
    weight: float
    prompt: tuple[re.Pattern, ...]
    commands: tuple[re.Pattern, ...]
    tools: dict
    signals: dict


@dataclass
class TurnFacts:
    prompt: str = ""
    permission_mode: str | None = None
    tools: Counter = field(default_factory=Counter)  # tool name -> calls
    commands: list[str] = field(default_factory=list)  # shell signatures, in order
    errors: int = 0
    markdown_edits: int = 0
    repeated_after_error: int = 0


@lru_cache
def load_rules(path: str | None = None) -> tuple[tuple[Category, ...], str]:
    file = Path(path or os.environ.get("WAMT_RULES_FILE") or RULES_FILE)
    data = yaml.safe_load(file.read_text(encoding="utf-8"))
    cats = tuple(
        Category(
            name=c["name"],
            weight=float(c.get("weight", 3)),
            prompt=tuple(re.compile(p, re.IGNORECASE) for p in c.get("prompt") or []),
            commands=tuple(re.compile(p, re.IGNORECASE) for p in c.get("commands") or []),
            tools=dict(c.get("tools") or {}),
            signals=dict(c.get("signals") or {}),
        )
        for c in data["categories"]
    )
    return cats, data.get("fallback", "chat")


def category_names() -> list[str]:
    return [c.name for c in load_rules()[0]]


def _signals(f: TurnFacts) -> dict[str, float]:
    total_tools = sum(f.tools.values())
    read_tools = sum(f.tools[t] for t in ("Read", "Grep", "Glob", "LS"))
    edit_tools = sum(f.tools[t] for t in ("Edit", "MultiEdit", "Write", "NotebookEdit"))
    return {
        "tool_errors": min(f.errors, 4),
        "repeated_command_after_error": min(f.repeated_after_error, 3),
        "plan_mode": 1.0 if f.permission_mode == "plan" else 0.0,
        "markdown_edits": min(f.markdown_edits, 4),
        "no_tools": 1.0 if total_tools == 0 else 0.0,
        "read_only": 1.0 if read_tools >= 3 and edit_tools == 0 and not f.commands else 0.0,
    }


def score(f: TurnFacts) -> dict[str, float]:
    cats, _ = load_rules()
    sig = _signals(f)
    # "continue" carries no intent of its own: let the tools decide.
    prompt = "" if CONTINUATION.match(f.prompt or "") and len((f.prompt or "").split()) <= 6 else (f.prompt or "")
    head = prompt[:1500]
    scores: dict[str, float] = {}
    for c in cats:
        s = 0.0
        if head and any(p.search(head) for p in c.prompt):
            s += c.weight
        if c.commands:
            s += min(sum(1 for cmd in f.commands if any(p.search(cmd) for p in c.commands)), 4)
        for tool, w in c.tools.items():
            s += float(w) * min(f.tools.get(tool, 0), 5)
        for name, w in c.signals.items():
            s += float(w) * sig.get(name, 0.0)
        scores[c.name] = round(s, 2)
    return scores


def classify(f: TurnFacts) -> tuple[str, float, dict[str, float]]:
    """Returns (category, confidence 0..1, scores)."""
    _, fallback = load_rules()
    scores = score(f)
    best = max(scores.items(), key=lambda kv: kv[1])  # first listed wins ties
    total = sum(v for v in scores.values() if v > 0)
    if best[1] <= 0:
        return fallback, 0.0, scores
    return best[0], round(best[1] / total, 2), scores


def facts_json(scores: dict[str, float]) -> str:
    return json.dumps({k: v for k, v in scores.items() if v > 0}, sort_keys=True)
