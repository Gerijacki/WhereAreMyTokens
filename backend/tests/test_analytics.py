from collections import Counter
from datetime import UTC, datetime, timedelta

from wamt.analytics.cache import Call, detect_rebuilds
from wamt.analytics.classify import TurnFacts, classify
from wamt.analytics.commands import command_signature, normalize_path, tool_signature
from wamt.collector.parser import parse_record


def test_command_signature_strips_cd_filters_and_args():
    cases = {
        'cd "c:\\x\\proj" && pnpm build 2>&1 | tail -n 5 && pnpm exec vitest run --coverage':
            "pnpm build && pnpm exec vitest",
        'cd "c:/x" && FULL_SHA=$(git rev-parse HEAD) && gh api repos/a/b/runs?sha=$FULL_SHA': "gh api",
        "cd /c/x && for f in a.md b.md; do cat \"$f\"; done": "cat",
        "git commit -m \"$(cat <<'EOF'\nfix: thing\n\nbody\nEOF\n)\"": "git commit",
        'python -c "\nprint(1)\n" && sed -i s/a/b/ f': "python (inline script) && sed",
        "docker compose exec -T db psql": "docker compose exec",
        "gh run list --branch main --limit 3": "gh run list",
        "GODOT=/c/g.exe && \"$GODOT\" --headless -s run.gd": "$godot",
        "cd x": None,
    }
    for cmd, expected in cases.items():
        assert command_signature(cmd) == expected, cmd


def test_paths_normalize_across_shells_and_case():
    root = r"c:\Users\me\proj"
    assert normalize_path(r"C:\Users\me\proj\src\App.tsx", root) == "src/App.tsx"
    assert normalize_path("/c/Users/me/proj/src/App.tsx", root) == "src/App.tsx"
    assert tool_signature("Read", r"c:\Users\me\proj\package.json", root) == "package.json"


def _facts(prompt="", **tools) -> TurnFacts:
    return TurnFacts(prompt=prompt, tools=Counter(tools))


def test_classifier_uses_prompt_tools_and_signals():
    assert classify(_facts("fix the login bug, it crashes", Edit=2))[0] == "debugging"
    assert classify(_facts("com funciona el sistema d'autenticació?", Read=6, Grep=3))[0] == "exploration"
    assert classify(_facts("afegeix un endpoint per exportar CSV", Edit=4, Write=2))[0] == "coding"
    assert classify(TurnFacts(prompt="design the new sync", permission_mode="plan"))[0] == "planning"
    f = _facts("busca les millors alternatives", WebSearch=3, WebFetch=2)
    assert classify(f)[0] == "research"
    f = _facts("continua", Bash=3)
    f.commands = ["pnpm test", "pnpm exec vitest", "pnpm test"]
    assert classify(f)[0] == "testing"
    assert classify(_facts("thanks!"))[0] == "chat"


def test_builtin_slash_commands_become_events_not_prompts():
    base = {"sessionId": "s", "uuid": "u1", "timestamp": "2026-09-01T10:00:00Z", "type": "user"}
    rec = {**base, "message": {"role": "user", "content":
           "<command-name>/model</command-name>\n<command-message>model</command-message>\n"
           "<command-args>sonnet</command-args>"}}
    parsed = parse_record(rec)
    assert parsed.prompt is None
    assert (parsed.event.kind, parsed.event.cause) == ("command", "/model sonnet")
    rec["message"]["content"] = ("<command-name>/review-pr</command-name>\n<command-message>review-pr"
                                 "</command-message>\n<command-args>42</command-args>")
    assert parse_record(rec).prompt.text == "/review-pr 42"


def test_cache_rebuild_causes():
    t0 = datetime(2026, 9, 1, tzinfo=UTC)

    def call(i, minutes, model="claude-sonnet-5", read=0, w5=0, w1h=0):
        return Call(id=f"c{i}", ts=t0 + timedelta(minutes=minutes), model=model, input_tokens=1,
                    cache_write_5m=w5, cache_write_1h=w1h, cache_read=read)

    calls = [
        call(0, 0, w5=100_000),                     # first call: initial write, not a rebuild
        call(1, 1, read=100_000, w5=2_000),         # healthy
        call(2, 30, w5=102_000),                    # 29 min idle > 5 min TTL
        call(3, 31, read=102_000, w5=1_000),
        call(4, 32, model="claude-opus-5-5", w5=103_000),  # model switch
        call(5, 33, model="claude-opus-5-5", w5=103_000),  # nothing explains it: prefix changed
    ]
    rebuilds = detect_rebuilds(calls, compactions=[])
    assert [(r.call_id, r.cause) for r in rebuilds] == [
        ("c2", "idle_expired"), ("c4", "model_switch"), ("c5", "prefix_change")]
    assert rebuilds[0].wasted_usd > 0
    compact = detect_rebuilds(calls[:3], compactions=[t0 + timedelta(minutes=10)])
    assert compact[0].cause == "compaction"
