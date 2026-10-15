"""End-to-end: synthetic transcripts with known patterns -> ingest -> insights + API."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from wamt.collector.ingest import scan
from wamt.db import init_engine
from wamt.insights.engine import refresh

ROOT = r"C:\demo\shop"
SLUG = "C--demo-shop"


class Transcript:
    def __init__(self, session: str, start: datetime):
        self.session, self.ts, self.lines, self.n = session, start, [], 0

    def _rec(self, **kw):
        self.n += 1
        self.ts += timedelta(seconds=20)
        base = {"sessionId": self.session, "uuid": f"{self.session}-{self.n}", "timestamp": self.ts.isoformat(),
                "cwd": ROOT, "isSidechain": False}
        self.lines.append(json.dumps({**base, **kw}))

    def prompt(self, text: str, gap_minutes: float = 0):
        self.ts += timedelta(minutes=gap_minutes)
        self._rec(type="user", message={"role": "user", "content": text}, origin={"kind": "human"})

    def call(self, tools=(), context=200_000, write=2_000, model="claude-opus-5-5", results=None):
        mid = f"msg-{self.session}-{self.n}"
        content = [{"type": "tool_use", "id": f"tu-{self.session}-{self.n}-{i}", "name": name, "input": inp}
                   for i, (name, inp) in enumerate(tools)]
        usage = {"input_tokens": 5, "output_tokens": 300, "cache_read_input_tokens": context - write,
                 "cache_creation_input_tokens": write,
                 "cache_creation": {"ephemeral_5m_input_tokens": write, "ephemeral_1h_input_tokens": 0}}
        self._rec(type="assistant", message={"id": mid, "model": model, "role": "assistant", "content": content,
                                             "usage": usage})
        if tools:
            out = results or ["ok"] * len(tools)
            self._rec(type="user", message={"role": "user", "content": [
                {"type": "tool_result", "tool_use_id": f"tu-{self.session}-{self.n - 1}-{i}", "content": r,
                 "is_error": r.startswith("FAIL")} for i, r in enumerate(out)]})


def bash(cmd):
    return ("Bash", {"command": f'cd "{ROOT}" && {cmd}'})


@pytest.fixture
def client(tmp_path):
    root = tmp_path / "projects"
    (root / SLUG).mkdir(parents=True)
    start = datetime.now(UTC) - timedelta(days=5)
    for s in range(4):
        t = Transcript(f"sess{s}", start + timedelta(days=s))
        t.prompt("Run the release checks for the shop and tell me if something is broken")
        for cmd in ("pnpm lint 2>&1 | tail -20", "pnpm typecheck", "pnpm test:run", "pnpm build"):
            t.call([bash(cmd)])
        t.call([("Read", {"file_path": ROOT + r"\src\config.ts"})])
        t.call([("Read", {"file_path": ROOT + r"\pnpm-lock.yaml"})], results=["x" * 120_000])
        for _ in range(4):
            t.call([bash("pnpm test:run")], results=["FAIL cart.test.ts"])
            t.call([("Edit", {"file_path": ROOT + r"\src\cart.ts"})])
        t.call()
        t.prompt("thanks, explain how the cart works", gap_minutes=40)  # cache expired meanwhile
        t.call(write=180_000)
        for _ in range(25):
            t.call([("Read", {"file_path": ROOT + r"\src\cart.ts"})])
        (root / SLUG / f"sess{s}.jsonl").write_text("\n".join(t.lines) + "\n", encoding="utf-8")
    init_engine(f"sqlite:///{tmp_path / 'test.db'}")
    scan(root, "test")
    refresh()
    from wamt.main import app

    return TestClient(app)


def by_type(items):
    out = {}
    for i in items:
        out.setdefault(i["type"], []).append(i)
    return out


def test_miners_find_the_planted_patterns(client):
    items = client.get("/api/insights").json()["items"]
    types = by_type(items)
    for expected in ("command_sequence", "fix_loop", "context_bloat", "file_rereads", "repeated_prompt",
                     "allowlist", "large_context", "cache_rebuild", "model_fit"):
        assert expected in types, f"missing {expected}: {sorted(types)}"

    seq = types["command_sequence"][0]
    assert "pnpm lint" in seq["title"] and "pnpm build" in seq["title"]
    assert seq["artifact"]["path"].startswith(".claude/skills/")
    assert "pnpm lint 2>&1 | tail -20 && pnpm typecheck" in seq["artifact"]["content"]

    bloat = types["context_bloat"][0]
    assert "pnpm-lock.yaml" in bloat["title"]
    assert json.loads(bloat["artifact"]["content"]) == {"permissions": {"deny": ["Read(./pnpm-lock.yaml)"]}}

    allow = json.loads(types["allowlist"][0]["artifact"]["content"])["permissions"]["allow"]
    assert "Bash(pnpm typecheck:*)" in allow and "Bash(pnpm lint:*)" in allow

    loop = types["fix_loop"][0]
    hook = json.loads(loop["artifact"]["content"])["hooks"]["PostToolUse"][0]
    assert hook["matcher"] == "Edit|Write|MultiEdit"

    assert types["model_fit"][0]["artifact"]["path"] == ".claude/agents/explorer.md"
    assert all(i["est_usd_month"] >= 0 for i in items)


def test_insight_status_survives_refresh(client):
    first = client.get("/api/insights").json()["items"][0]
    assert client.patch(f"/api/insights/{first['id']}", json={"status": "done"}).status_code == 200
    client.post("/api/insights/refresh")
    done = client.get("/api/insights?status=done").json()["items"]
    assert [i["id"] for i in done] == [first["id"]]
    assert first["id"] not in {i["id"] for i in client.get("/api/insights").json()["items"]}


def test_m2_endpoints(client):
    cats = client.get("/api/categories?days=0").json()
    assert "testing" in cats["categories"]
    assert sum(c["prompts"] for c in cats["by_category"]) == 8

    tools = client.get("/api/tools?days=0").json()
    cmds = {c["signature"]: c for c in tools["commands"]}
    assert cmds["pnpm test:run"]["calls"] == 20 and cmds["pnpm test:run"]["errors"] == 16
    assert tools["biggest_results"][0]["target"] == "pnpm-lock.yaml"

    cache = client.get("/api/cache?days=0").json()
    assert {c["cause"] for c in cache["by_cause"]} == {"idle_expired"}
    assert cache["totals"]["saved_usd"] > 0

    limits = client.get("/api/limits?days=30").json()
    assert len(limits["blocks"]) == 4
    assert len(limits["heatmap"]) == 7 and len(limits["heatmap"][0]) == 24


def test_manual_category_sticks(client):
    detail = client.get("/api/sessions/sess0").json()
    turn = detail["turns"][0]
    assert client.patch(f"/api/turns/{turn['id']}", json={"category": "ops"}).json()["category_source"] == "manual"
    client.post("/api/admin/reclassify")
    again = client.get("/api/sessions/sess0").json()["turns"][0]
    assert (again["category"], again["category_source"]) == ("ops", "manual")
    assert client.patch(f"/api/turns/{turn['id']}", json={"category": "nope"}).status_code == 422
    reset = client.patch(f"/api/turns/{turn['id']}", json={"category": None}).json()
    assert reset["category_source"] == "rules"
