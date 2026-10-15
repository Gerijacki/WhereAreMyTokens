"""Synthetic Claude Code transcripts for demos, screenshots and tests.

Everything here is fictional: projects, prompts, files and commands. The generator plants the
patterns the insight miners look for (repeated check sequences, fix loops, re-read files, huge
lockfile reads, idle gaps that expire the cache, compactions, model switches, subagents) so
every dashboard has something to show.
"""

from __future__ import annotations

import json
import random
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from wamt.collector.ingest import slugify

ROOT = "/home/demo/code"
MODELS = [("claude-sonnet-5-5", 0.62), ("claude-opus-5-5", 0.30), ("claude-sonnet-5", 0.08)]
SUBAGENT_MODEL = "claude-haiku-5-5"

PROJECTS = {
    "acme-shop": {
        "files": ["src/config.ts", "package.json", "src/cart/cart.ts", "src/cart/cart.test.ts", "src/api/client.ts",
                  "src/pages/Checkout.tsx", "vite.config.ts", "README.md"],
        "check": ["pnpm lint 2>&1 | tail -20", "pnpm typecheck", "pnpm test", "pnpm build 2>&1 | tail -5"],
        "test": "pnpm test -- src/cart",
        "lock": "pnpm-lock.yaml",
    },
    "billing-api": {
        "files": ["app/main.py", "app/models.py", "app/routes/invoices.py", "tests/test_invoices.py",
                  "pyproject.toml", "alembic/env.py", "README.md"],
        "check": ["ruff check .", "pytest -q"],
        "test": "pytest -q tests/test_invoices.py",
        "lock": "uv.lock",
    },
    "docs-site": {
        "files": ["docs/index.md", "docs/getting-started.md", "astro.config.mjs", "package.json", "README.md"],
        "check": ["pnpm build"],
        "test": "pnpm build",
        "lock": "pnpm-lock.yaml",
    },
    "infra": {
        "files": ["docker-compose.yml", "terraform/main.tf", "terraform/variables.tf", ".github/workflows/deploy.yml"],
        "check": ["terraform fmt -check", "terraform validate"],
        "test": "terraform plan -no-color | tail -40",
        "lock": ".terraform.lock.hcl",
    },
}

# Prompt templates: {x}/{y} are filled from VOCAB so ordinary prompts don't look like repeats.
PROMPTS = {
    "coding": [
        "Add a {feature} to the {area} and wire it to the API",
        "Implement {feature} for the {area}, keep the existing style",
        "Create a reusable {component} component for the {area}",
        "Refactor the {area} to remove the duplicated {thing} logic",
        "Make the {area} support {feature}",
    ],
    "debugging": [
        "The {area} breaks when {condition}, fix it",
        "Tests fail with '{error}' after the last change in the {area}",
        "There's a bug in the {thing} handling of the {area}: {condition}",
        "Why does the {area} crash when {condition}?",
    ],
    "exploration": [
        "Explain how the {area} works, from the entry point to the {thing}",
        "How is the {thing} computed in the {area}? Walk me through the code",
        "Analyze where the {thing} logic lives and what depends on it",
    ],
    "testing": [
        "Write unit tests for the {thing} in the {area}, including edge cases",
        "Add tests for the {area} {thing} and raise coverage",
    ],
    "ops": [
        "Commit the {area} changes with a good message and push",
        "The deploy pipeline is red after the {area} change, check the latest run and fix it",
        "Bump the {thing} dependencies and make sure the build still passes",
    ],
    "planning": [
        "Design how we should add {feature} to the {area}. Propose an approach before writing code",
        "Plan the migration of the {area} {thing} to a cleaner architecture",
    ],
    "research": [
        "Search for best practices on {thing} in payment APIs and compare the options",
        "Find the latest docs about {feature} and tell me what changed",
    ],
    "review": [
        "Review the open pull request for the {area} and tell me if it's safe to merge",
        "Do a code review of the {area}, focus on the {thing} handling",
    ],
    "docs": [
        "Update the README with the new {area} setup steps",
        "Document the {area} {thing} in the docs folder",
    ],
    "chat": ["thanks!", "ok, makes sense", "what would you do next?", "nice"],
}
VOCAB = {
    "feature": ["discount codes", "multi-currency", "dark mode", "CSV export", "rate limiting", "webhooks",
                "pagination", "search filters", "audit logging", "retry with backoff", "i18n", "feature flags"],
    "area": ["checkout", "cart", "invoices endpoint", "auth flow", "admin dashboard", "settings page",
             "billing worker", "email templates", "deploy pipeline", "product catalog", "API client"],
    "component": ["Button", "Modal", "DataTable", "DatePicker", "Toast", "Pagination", "EmptyState"],
    "thing": ["tax", "totals", "session", "retry", "validation", "caching", "currency", "permissions", "timezone"],
    "condition": ["a coupon and free shipping apply together", "the user has no address", "the list is empty",
                  "two requests arrive at once", "the token expires mid-request", "the locale is not English"],
    "error": ["TypeError: cannot read properties of undefined (reading 'id')", "KeyError: 'currency'",
              "AssertionError: expected 42 to equal 40", "ECONNRESET", "IntegrityError: duplicate key"],
}


def _fill(template: str, rng: random.Random) -> str:
    return re.sub(r"\{(\w+)\}", lambda m: rng.choice(VOCAB[m.group(1)]), template)


CATEGORY_WEIGHTS = {"coding": 30, "debugging": 18, "exploration": 12, "testing": 9, "ops": 10, "planning": 7,
                    "research": 4, "review": 5, "docs": 4, "chat": 5}
# Planted repeats so the "repeated prompt" and "repeated sequence" insights fire.
RELEASE_PROMPT = "Run the release checks for the shop and fix anything that fails before I deploy"
SUMMARY_PROMPT = "Summarize what changed since the last commit and whether anything looks risky"


@dataclass
class Session:
    project: str
    start: datetime
    rng: random.Random
    model: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    lines: list[str] = field(default_factory=list)
    sub_lines: dict[str, list[str]] = field(default_factory=dict)
    context: int = 0
    last_call: datetime | None = None

    def __post_init__(self):
        self.ts = self.start
        self.cwd = f"{ROOT}/{self.project}"
        self.context = self.rng.randint(18_000, 26_000)  # system prompt + tools + CLAUDE.md

    # -- low level ------------------------------------------------------------------------------
    def _tick(self, lo: float = 2, hi: float = 25) -> datetime:
        self.ts += timedelta(seconds=self.rng.uniform(lo, hi))
        return self.ts

    def _rec(self, target: list[str] | None = None, **kw) -> str:
        uid = str(uuid.uuid4())
        rec = {"sessionId": self.id, "uuid": uid, "timestamp": self.ts.isoformat().replace("+00:00", "Z"),
               "cwd": self.cwd, "gitBranch": "main", "version": "2.1.300", "entrypoint": "cli",
               "isSidechain": False, **kw}
        (self.lines if target is None else target).append(json.dumps(rec))
        return uid

    def _call(self, tools: list[tuple[str, dict, int, bool]], model: str | None = None, sidechain: str | None = None,
              out_tokens: int | None = None) -> None:
        """One API response, optionally with tool calls and their results (name, input, result chars, error)."""
        model = model or self.model
        self._tick()
        gap = (self.ts - self.last_call).total_seconds() if self.last_call else 0
        expired = gap > 3600  # Claude Code uses 1h cache writes on subscriptions
        new_tokens = self.rng.randint(150, 900)
        if expired or self.last_call is None:
            read, write = 0, self.context + new_tokens
        else:
            read, write = self.context, new_tokens
        out = out_tokens or self.rng.randint(80, 1400)
        mid = f"msg_{uuid.uuid4().hex[:24]}"
        content = [{"type": "tool_use", "id": f"toolu_{uuid.uuid4().hex[:24]}", "name": n, "input": i}
                   for n, i, _, _ in tools]
        usage = {"input_tokens": self.rng.randint(1, 12), "output_tokens": out, "cache_read_input_tokens": read,
                 "cache_creation_input_tokens": write,
                 "cache_creation": {"ephemeral_5m_input_tokens": 0, "ephemeral_1h_input_tokens": write}}
        target = self.sub_lines.setdefault(sidechain, []) if sidechain else None
        extra = {"agentId": sidechain} if sidechain else {}
        self._rec(target, type="assistant", requestId=f"req_{uuid.uuid4().hex[:24]}", isSidechain=bool(sidechain),
                  message={"id": mid, "model": model, "role": "assistant", "content": content, "usage": usage},
                  **extra)
        if not sidechain:
            self.context += new_tokens + out
            self.last_call = self.ts
        if tools:
            self._tick(1, 40)
            results = [{"type": "tool_result", "tool_use_id": c["id"], "content": "x" * chars, "is_error": err}
                       for c, (_, _, chars, err) in zip(content, tools, strict=True)]
            self._rec(target, type="user", isSidechain=bool(sidechain), message={"role": "user", "content": results},
                      **extra)
            if not sidechain:
                self.context += sum(chars for _, _, chars, _ in tools) // 4

    def prompt(self, text: str, plan: bool = False, gap_minutes: float = 0) -> None:
        self.ts += timedelta(minutes=gap_minutes)
        self._tick(20, 180)
        self._rec(type="user", message={"role": "user", "content": text}, origin={"kind": "human"},
                  permissionMode="plan" if plan else "default")

    def command(self, name: str, args: str = "") -> None:
        self._tick(10, 60)
        self._rec(type="user", message={"role": "user", "content": f"<command-name>{name}</command-name>\n"
                                                                    f"<command-message>{name[1:]}</command-message>\n"
                                                                    f"<command-args>{args}</command-args>"})

    def compact(self) -> None:
        self.command("/compact")
        self._tick(30, 90)
        self._rec(type="system", subtype="compact_boundary", content="Conversation compacted",
                  compactMetadata={"trigger": "manual", "preTokens": self.context})
        self.context = self.rng.randint(22_000, 34_000)
        self.last_call = None  # the next call writes the compacted context

    # -- tools ----------------------------------------------------------------------------------
    def path(self, rel: str) -> str:
        return f"{self.cwd}/{rel}"

    def bash(self, cmd: str, chars: int | None = None, error: bool = False):
        return ("Bash", {"command": f'cd "{self.cwd}" && {cmd}'}, chars or self.rng.randint(200, 2500), error)

    def read(self, rel: str, chars: int | None = None):
        return ("Read", {"file_path": self.path(rel)}, chars or self.rng.randint(1500, 14000), False)

    def edit(self, rel: str):
        return ("Edit", {"file_path": self.path(rel), "old_string": "a", "new_string": "b"}, 120, False)

    def run(self, *tools, model: str | None = None) -> None:
        for t in tools:
            self._call([t], model=model)

    def answer(self) -> None:
        self._call([], out_tokens=self.rng.randint(300, 2500))

    def subagent(self, description: str, reads: list[str]) -> None:
        self._call([("Agent", {"description": description, "subagent_type": "Explore"}, 3000, False)])
        agent_id = uuid.uuid4().hex[:17]
        for rel in reads:
            self._call([("Read", {"file_path": self.path(rel)}, self.rng.randint(2000, 9000), False)],
                       model=SUBAGENT_MODEL, sidechain=agent_id)
        self._call([], model=SUBAGENT_MODEL, sidechain=agent_id)


def _turn(s: Session, category: str, cfg: dict) -> None:
    r = s.rng
    files = cfg["files"]
    s.prompt(_fill(r.choice(PROMPTS[category]), r), plan=category == "planning")
    if category == "coding":
        for f in r.sample(files, k=min(len(files), r.randint(3, 6))):
            s.run(s.read(f))
        for _ in range(r.randint(4, 10)):
            s.run(s.edit(r.choice(files)))
        s.run(s.bash(cfg["check"][min(1, len(cfg["check"]) - 1)]))
    elif category == "debugging":
        s.run(s.bash(cfg["test"], chars=r.randint(2500, 9000), error=True), s.read(files[0]), s.read(files[2]))
        for i in range(r.randint(2, 4)):  # fix loop
            s.run(s.edit(files[2]), s.bash(cfg["test"], chars=r.randint(2500, 9000), error=i < 2))
    elif category == "exploration":
        if r.random() < 0.5:
            s.subagent("Map the project structure", r.sample(files, k=min(4, len(files))))
        else:
            s.run(("Glob", {"pattern": "src/**/*.ts"}, 600, False), ("Grep", {"pattern": "auth"}, 1800, False))
            for f in r.sample(files, k=min(len(files), 4)):
                s.run(s.read(f))
    elif category == "testing":
        s.run(s.read(files[2]), ("Write", {"file_path": s.path(files[3])}, 100, False), s.bash(cfg["test"]),
              s.bash(cfg["test"]))
    elif category == "ops":
        s.run(s.bash("git status --short"), s.bash("git diff --stat"),
              s.bash('git add -A && git commit -m "update"'), s.bash("git push origin main"),
              s.bash("gh run list --limit 3"))
    elif category == "planning":
        for f in r.sample(files, k=min(3, len(files))):
            s.run(s.read(f))
        s.run(("AskUserQuestion", {"question": "Which approach?"}, 300, False),
              ("ExitPlanMode", {"plan": "..."}, 2500, False))
    elif category == "research":
        s.run(("WebSearch", {"query": "best practices"}, 4000, False),
              ("WebFetch", {"url": "https://docs.example.com/guide"}, 9000, False))
    elif category == "review":
        s.run(s.bash("gh pr view 42 --json title,body,files"), s.bash("gh pr diff 42", chars=12000),
              s.read(files[2]))
    elif category == "docs":
        s.run(s.read("README.md"), s.edit("README.md"), s.edit("README.md"))
    s.answer()


def _release_checks(s: Session, cfg: dict) -> None:
    """Planted: the same multi-step check sequence, asked with the same words, again and again."""
    s.prompt(RELEASE_PROMPT)
    s.run(s.read("package.json"), s.read("src/config.ts"))
    for cmd in cfg["check"]:
        s.run(s.bash(cmd, chars=s.rng.randint(400, 6000)))
    s.answer()


def generate(out_dir: Path, days: int = 30, seed: int = 7) -> int:
    rng = random.Random(seed)
    out_dir = Path(out_dir)
    now = datetime.now(UTC).replace(microsecond=0)
    start_day = (now - timedelta(days=days)).replace(hour=0, minute=0, second=0)
    sessions: list[Session] = []
    day = start_day
    while day.date() <= now.date():
        weekday = day.weekday()
        n = rng.choice([0, 1, 1, 2, 2, 3]) if weekday < 5 else rng.choice([0, 0, 0, 1])
        is_today = day.date() == now.date()
        if is_today:
            n = 1
        for _ in range(n):
            project = rng.choices(list(PROJECTS), weights=[45, 25, 12, 18])[0]
            model = rng.choices([m for m, _ in MODELS], weights=[w for _, w in MODELS])[0]
            if is_today:
                begin = now - timedelta(minutes=rng.randint(70, 110))
            else:
                begin = day + timedelta(hours=rng.choice([9, 10, 11, 14, 15, 16, 17, 21]), minutes=rng.randint(0, 59))
            s = Session(project=project, start=begin, rng=rng, model=model)
            cfg = PROJECTS[project]
            turns = rng.randint(5, 14) if not is_today else 5
            for t in range(turns):
                if is_today and s.ts > now - timedelta(minutes=8):
                    break
                if project == "acme-shop" and rng.random() < 0.18:
                    _release_checks(s, cfg)
                elif rng.random() < 0.05:
                    s.prompt(SUMMARY_PROMPT)
                    s.run(s.bash("git diff --stat"), s.bash("git log --oneline -10"))
                    s.answer()
                else:
                    cat = rng.choices(list(CATEGORY_WEIGHTS), weights=list(CATEGORY_WEIGHTS.values()))[0]
                    _turn(s, cat, cfg)
                if t == 2 and rng.random() < 0.3:
                    s.run(s.read(cfg["lock"], chars=rng.randint(90_000, 260_000)))  # planted context bloat
                if rng.random() < 0.08 and not is_today:
                    s.prompt("thanks, let's continue", gap_minutes=rng.randint(70, 180))  # cache expires
                    s.answer()
                if s.context > 160_000 and rng.random() < 0.5:
                    s.compact()
                if t == 1 and rng.random() < 0.06:
                    s.command("/model", "sonnet")
                    s.model = "claude-sonnet-5-5"
            sessions.append(s)
        day += timedelta(days=1)

    for s in sessions:
        proj_dir = out_dir / slugify(s.cwd)
        proj_dir.mkdir(parents=True, exist_ok=True)
        title = {"type": "ai-title", "aiTitle": _title(s), "sessionId": s.id}
        (proj_dir / f"{s.id}.jsonl").write_text("\n".join([*s.lines, json.dumps(title)]) + "\n", encoding="utf-8")
        for agent_id, lines in s.sub_lines.items():
            sub = proj_dir / s.id / "subagents"
            sub.mkdir(parents=True, exist_ok=True)
            (sub / f"agent-{agent_id}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(sessions)


def _title(s: Session) -> str:
    first = next((json.loads(line) for line in s.lines if '"origin"' in line), None)
    text = (first or {}).get("message", {}).get("content", "Session")
    return text if len(text) <= 60 else text[:57].rsplit(" ", 1)[0] + "…"
