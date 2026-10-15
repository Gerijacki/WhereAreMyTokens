"""Ready-to-paste files for each kind of recommendation (Claude Code skills, slash commands,
subagents, settings.json snippets, CLAUDE.md blocks)."""

from __future__ import annotations

import json
import re


def slug(text: str, fallback: str = "task", max_words: int = 4) -> str:
    words = re.findall(r"[a-z0-9]+", text.lower())
    out = "-".join(words[:max_words])
    return out or fallback


def skill(name: str, description: str, body: str) -> tuple[str, str, str]:
    content = f"---\nname: {name}\ndescription: {description}\n---\n\n{body.strip()}\n"
    return "skill", f".claude/skills/{name}/SKILL.md", content


def slash_command(name: str, description: str, prompt: str) -> tuple[str, str, str]:
    content = f"---\ndescription: {description}\n---\n\n{prompt.strip()}\n\n$ARGUMENTS\n"
    return "command", f".claude/commands/{name}.md", content


def subagent(name: str, description: str, model: str, tools: list[str], body: str) -> tuple[str, str, str]:
    content = (f"---\nname: {name}\ndescription: {description}\nmodel: {model}\ntools: {', '.join(tools)}\n---\n\n"
               f"{body.strip()}\n")
    return "agent", f".claude/agents/{name}.md", content


def settings(snippet: dict) -> tuple[str, str, str]:
    return "settings", ".claude/settings.json", json.dumps(snippet, indent=2) + "\n"


def claude_md(block: str) -> tuple[str, str, str]:
    return "claude_md", "CLAUDE.md", block.strip() + "\n"


def tip(text: str) -> tuple[str, str | None, str]:
    return "tip", None, text.strip() + "\n"
