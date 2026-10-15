"""Insight miners. Each takes the Dataset and yields Finding objects.

Savings are *estimates* and documented per miner. The main unit is an avoided API round
trip: in Claude Code every tool call is followed by another model call that re-reads
the whole context, so a session's average cost per call is a fair price for one call.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter, defaultdict
from collections.abc import Iterator
from dataclasses import dataclass, field

from wamt.analytics.commands import SHELL_TOOLS, allowlist_rule, split_segments
from wamt.insights import artifacts as art
from wamt.insights.data import Dataset, Tool, carry_cost
from wamt.pricing import cost_usd, price_for

# Commands safe to pre-approve: they read state or run project checks, never publish or delete.
SAFE_PREFIXES = (
    "git status", "git diff", "git log", "git show", "git branch", "git rev-parse", "git remote", "git fetch",
    "ls", "pwd", "tree", "wc", "du", "which", "where",
    "pnpm typecheck", "pnpm lint", "pnpm test", "pnpm build", "pnpm exec vitest", "pnpm exec tsc", "pnpm exec eslint",
    "npm test", "yarn test", "yarn lint", "yarn build", "npx tsc", "npx eslint",
    "pytest", "ruff", "mypy", "go test", "go build", "go vet", "cargo test", "cargo check", "cargo build",
    "cargo clippy", "gh run list", "gh run view", "gh pr view", "gh pr list", "gh pr diff", "gh pr checks",
    "gh issue view", "gh issue list", "docker ps", "docker compose ps", "docker compose logs", "make test",
)
EXPLORATION_TOOLS = {"Read", "Grep", "Glob", "LS"}
CHEAP_CATEGORIES = {"exploration", "chat", "docs", "review", "research"}
EXPENSIVE_MODEL = re.compile(r"claude-(opus|fable|mythos)")
FIT_TARGET_MODEL = "claude-sonnet-5-5"
BLOAT_TOKENS = 15_000
MAX_SEQUENCES_PER_PROJECT = 5
LOOKUP_COMMANDS = {"grep", "rg", "cat", "ls", "head", "tail", "find", "sed", "awk", "wc", "tree", "pwd", "type",
                   "get-content", "get-childitem", "select-string"}
LARGE_CONTEXT = 150_000
TARGET_CONTEXT = 60_000
# English / Catalan / Spanish function words, ignored when comparing prompts.
STOPWORDS = {
    "a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "is", "it",
    "this", "that", "i", "you", "me", "my", "we", "our", "be", "do", "it's", "al", "el",
    "la", "els", "les", "de", "del", "dels", "en", "per", "amb", "que", "es", "és", "un",
    "una", "uns", "unes", "ho", "li", "em", "et", "ens", "us", "no", "si", "lo", "los",
    "las", "y", "o", "con", "para", "por", "se", "le", "te", "nos",
}


@dataclass
class Finding:
    type: str
    key: str
    title: str
    summary: str
    project_id: int | None
    occurrences: int
    est_tokens: int
    est_usd: float
    evidence: list[dict] = field(default_factory=list)
    artifact: tuple[str, str | None, str] | None = None
    severity: str | None = None  # computed from est_usd_month when None


def _n(count: int, noun: str) -> str:
    return f"{count:,} {noun}{'' if count == 1 else 's'}"


def _evidence(ds: Dataset, tool_or_turn_ids: list[tuple[str, str | None]], note: dict | None = None) -> list[dict]:
    out = []
    for session_id, turn_id in tool_or_turn_ids[:6]:
        t = ds.turns.get(turn_id) if turn_id else None
        s = ds.sessions.get(session_id)
        out.append({
            "session_id": session_id,
            "turn_id": turn_id,
            "session_title": s.title if s else None,
            "prompt": (t.prompt[:160] if t else None),
            "ts": t.ts.isoformat() if t else None,
            **(note or {}),
        })
    return out


def _main_shell(ds: Dataset) -> list[Tool]:
    return [t for t in ds.tools if t.name in SHELL_TOOLS and t.signature and not t.is_sidechain]


def _strip_cd(cmd: str) -> str:
    """Drop the leading `cd <project> &&` Claude Code adds, keeping the rest of the line."""
    segs = split_segments(cmd)
    while segs and segs[0][1].split()[:1] in (["cd"], ["pushd"]):
        segs = segs[1:]
    if not segs:
        return cmd
    joiner = {"&&": " && ", "||": " || ", ";": "; ", "|": " | "}
    return segs[0][1] + "".join(joiner.get(sep, " ; ") + seg for sep, seg in segs[1:])


# --------------------------------------------------------------------------- allowlist

def allowlist(ds: Dataset) -> Iterator[Finding]:
    """Frequent read-only commands per project -> permission allowlist (saves prompts, not tokens)."""
    per_project: dict[int, Counter] = defaultdict(Counter)
    examples: dict[tuple[int, str], list] = defaultdict(list)
    for t in _main_shell(ds):
        pid = ds.project_of(t.session_id)
        for part in t.signature.split(" && "):
            if part.startswith(SAFE_PREFIXES):
                per_project[pid][part] += 1
                examples[(pid, part)].append((t.session_id, t.turn_id))
    for pid, counts in per_project.items():
        frequent = [(sig, n) for sig, n in counts.most_common() if n >= 3]
        if not frequent:
            continue
        rules = sorted({allowlist_rule(sig) for sig, _ in frequent})
        total = sum(n for _, n in frequent)
        if total < 8:
            continue
        listing = ", ".join(f"`{s}` ×{n}" for s, n in frequent[:6])
        yield Finding(
            type="allowlist", key=str(pid),
            title=f"Pre-approve {_n(len(rules), 'read-only command')} in {ds.project_name(pid)}",
            summary=(f"These commands ran {total} times and only read state or run checks: {listing}. "
                     "Allowing them in the project settings removes the permission prompts that interrupt "
                     "long runs. Review the list before merging it into .claude/settings.json."),
            project_id=pid, occurrences=total, est_tokens=0, est_usd=0.0,
            evidence=_evidence(ds, examples[(pid, frequent[0][0])]),
            artifact=art.settings({"permissions": {"allow": rules}}),
            severity="medium" if total >= 30 else "low",
        )


# --------------------------------------------------------------------------- sequences

def command_sequences(ds: Dataset, min_count: int = 3) -> Iterator[Finding]:
    """The same chain of separate shell calls repeated across turns -> one script / skill.

    Saving: (n - 1) round trips per occurrence at the session's average cost per call.
    """
    by_turn: dict[str, list[Tool]] = defaultdict(list)
    for t in _main_shell(ds):
        if t.turn_id:
            by_turn[t.turn_id].append(t)
    grams: dict[tuple[int, tuple[str, ...]], list[tuple[str, list[Tool]]]] = defaultdict(list)
    for turn_id, calls in by_turn.items():
        # Collapse immediate repeats (run, run, run) - those are fix loops, handled elsewhere.
        calls = [c for i, c in enumerate(calls) if i == 0 or c.signature != calls[i - 1].signature]
        sigs = [c.signature for c in calls]
        pid = ds.project_of(calls[0].session_id)
        seen: set[tuple[str, ...]] = set()
        for n in (4, 3, 2):
            for i in range(len(sigs) - n + 1):
                g = tuple(sigs[i:i + n])
                if len(set(g)) < 2 or g in seen or all(_is_lookup(x) for x in g):
                    continue
                seen.add(g)
                grams[(pid, g)].append((turn_id, calls[i:i + n]))
    candidates = []
    for (pid, g), occ in grams.items():
        turns = {t for t, _ in occ}
        if len(turns) < min_count:
            continue
        usd = sum((len(g) - 1) * ds.sessions[calls[0].session_id].cost_per_call for _, calls in occ)
        candidates.append((usd, pid, g, occ, turns))
    kept: list[tuple[int, tuple[str, ...], set[str]]] = []
    per_project: Counter = Counter()
    for usd, pid, g, occ, turns in sorted(candidates, key=lambda c: (-c[0], -len(c[2]))):
        # Skip variants of a sequence already reported (same prompts, overlapping commands).
        if any(p2 == pid and set(g) & set(g2) and len(turns & t2) >= 0.5 * len(turns) for p2, g2, t2 in kept):
            continue
        if per_project[pid] >= MAX_SEQUENCES_PER_PROJECT:
            continue
        kept.append((pid, g, turns))
        per_project[pid] += 1
        saved_calls = (len(g) - 1) * len(occ)
        example = [_strip_cd(c.target or "") for c in occ[-1][1]]
        # "pnpm lint → pnpm typecheck → pnpm test" -> "lint-typecheck-test": the verb of each step.
        verbs = dict.fromkeys(step.split(" && ")[-1].split()[-1] for step in g)
        name = art.slug(" ".join(verbs), "run-checks", 5)
        steps = "\n".join(f"{i + 1}. `{cmd}`" for i, cmd in enumerate(example))
        chain = " && ".join(example)
        body = (f"Run these steps as ONE shell call and report only failures (keep output short):\n\n"
                f"```bash\n{chain}\n```\n\nSteps, as last observed:\n{steps}\n")
        yield Finding(
            type="command_sequence", key=f"{pid}:{'|'.join(g)}",
            title=f"Bundle `{' → '.join(g)}` into one step ({len(turns)} prompts in {ds.project_name(pid)})",
            summary=(f"This chain of {len(g)} separate shell calls ran {len(occ)} times across {len(turns)} prompts "
                     f"in {ds.project_name(pid)}. Each extra call is a full model round trip that re-reads the "
                     f"context; a skill that runs them in one call saves about {saved_calls} round trips."),
            project_id=pid, occurrences=len(occ), est_tokens=0, est_usd=usd,
            evidence=_evidence(ds, [(calls[0].session_id, t) for t, calls in occ]),
            artifact=art.skill(name, f"Run {' then '.join(g)} in a single step and summarize failures.", body),
        )


def _is_lookup(signature: str) -> bool:
    return all(part.split(" ")[0] in LOOKUP_COMMANDS for part in signature.split(" && "))


# --------------------------------------------------------------------------- noisy commands

def noisy_commands(ds: Dataset, min_runs: int = 4, min_avg_tokens: int = 2_000) -> Iterator[Finding]:
    """A command re-run often whose output is large: every run's output is carried in context."""
    groups: dict[tuple[int, str], list[Tool]] = defaultdict(list)
    for t in _main_shell(ds):
        groups[(ds.project_of(t.session_id), t.signature)].append(t)
    for (pid, sig), runs in groups.items():
        if len(runs) < min_runs:
            continue
        avg = sum(r.result_tokens for r in runs) / len(runs)
        if avg < min_avg_tokens:
            continue
        keep = 300 / avg  # a summarized run would keep ~300 tokens
        usd = sum(carry_cost(ds, r) for r in runs) * (1 - keep)
        tokens = int(sum(r.result_tokens for r in runs) * (1 - keep))
        example = _strip_cd(runs[-1].target or sig)
        yield Finding(
            type="noisy_command", key=f"{pid}:{sig}",
            title=f"Trim the output of `{sig}` (~{int(avg):,} tokens per run, {len(runs)} runs)",
            summary=(f"`{sig}` ran {len(runs)} times in {ds.project_name(pid)} and returned about {int(avg):,} tokens "
                     "each time. That output stays in the conversation and is re-read by every later call. Wrap it "
                     "so it prints only a summary and the failures."),
            project_id=pid, occurrences=len(runs), est_tokens=tokens, est_usd=usd,
            evidence=_evidence(ds, [(r.session_id, r.turn_id) for r in runs[-6:]]),
            artifact=art.claude_md(
                f"## Running `{sig}`\n\nAlways limit its output, e.g.:\n\n```bash\n{example} 2>&1 | tail -n 40\n```\n\n"
                "Only show full output when the summary is not enough to locate the failure."),
        )


# --------------------------------------------------------------------------- fix loops

def fix_loops(ds: Dataset, min_runs_in_turn: int = 3) -> Iterator[Finding]:
    """The same command re-run several times inside one prompt, with failures: an edit/run loop."""
    by_turn_sig: dict[tuple[str, str], list[Tool]] = defaultdict(list)
    for t in _main_shell(ds):
        if t.turn_id:
            by_turn_sig[(t.turn_id, t.signature)].append(t)
    per_project: dict[tuple[int, str], list[list[Tool]]] = defaultdict(list)
    for (_turn, sig), runs in by_turn_sig.items():
        if len(runs) >= min_runs_in_turn and any(r.is_error for r in runs):
            per_project[(ds.project_of(runs[0].session_id), sig)].append(runs)
    for (pid, sig), loops in per_project.items():
        if len(loops) < 2:
            continue  # a one-off struggle is not a pattern
        runs = sum(len(x) for x in loops)
        extra = runs - len(loops)
        # Each extra iteration costs ~2 round trips (the run + the edit that follows).
        usd = sum((len(x) - 1) * 2 * ds.sessions[x[0].session_id].cost_per_call for x in loops) * 0.5
        first_cmd = sig.split(" && ")[0]
        yield Finding(
            type="fix_loop", key=f"{pid}:{sig}",
            title=f"Edit-and-retry loops on `{sig}` ({len(loops)} prompts, {runs} runs)",
            summary=(f"In {len(loops)} prompts in {ds.project_name(pid)}, `{sig}` was re-run {extra} extra times "
                     "after failing. Surfacing the error right after each edit (a PostToolUse hook) or running "
                     "the narrowest failing check shortens these loops."),
            project_id=pid, occurrences=runs, est_tokens=0, est_usd=usd,
            evidence=_evidence(ds, [(x[0].session_id, x[0].turn_id) for x in loops]),
            artifact=art.settings({"hooks": {"PostToolUse": [{
                "matcher": "Edit|Write|MultiEdit",
                # Exit code 2 feeds stderr back to Claude right after the edit.
                "hooks": [{"type": "command",
                           "command": f'out=$({first_cmd} 2>&1) || {{ echo "$out" | tail -n 30 >&2; exit 2; }}'}],
            }]}}),
        )


# --------------------------------------------------------------------------- context bloat

GENERATED = re.compile(r"(lock\.(json|yaml)|\.lock$|\.min\.(js|css)$|(^|/)(dist|build|out|coverage|\.next)/|\.map$|"
                       r"\.log$|\.svg$|\.snap$)", re.IGNORECASE)


def context_bloat(ds: Dataset) -> Iterator[Finding]:
    """Single tool results so large that carrying them for the rest of the session is expensive."""
    big = [t for t in ds.tools if t.result_tokens >= BLOAT_TOKENS and not t.is_sidechain]
    groups: dict[tuple[int, str, str], list[Tool]] = defaultdict(list)
    for t in big:
        groups[(ds.project_of(t.session_id), t.name, t.signature or t.name)].append(t)
    for (pid, tool, sig), items in groups.items():
        usd = sum(carry_cost(ds, t) for t in items) * 0.8
        tokens = sum(t.result_tokens for t in items)
        if tool == "Read" and GENERATED.search(sig):
            artifact = art.settings({"permissions": {"deny": [f"Read(./{sig})"]}})
            advice = "It looks generated; deny reading it and point Claude at the source instead."
        elif tool == "Read":
            artifact = art.claude_md(f"## Large files\n\n- `{sig}` is ~{tokens // len(items):,} tokens. Read it with "
                                     "`offset`/`limit` or Grep for the part you need instead of reading it whole.")
            advice = "Read only the needed range (offset/limit) or Grep for the part you need."
        else:
            artifact = art.claude_md(f"## Command output\n\n- Pipe `{sig}` through `tail -n 50` or `grep` — its full "
                                     f"output is ~{tokens // len(items):,} tokens.")
            advice = "Filter its output (tail/grep) before it reaches the conversation."
        yield Finding(
            type="context_bloat", key=f"{pid}:{tool}:{sig}",
            title=f"{tool} `{sig[:80]}` put ~{tokens // len(items):,} tokens into context ({len(items)}×)",
            summary=(f"Each result was cached and re-read by the calls that followed, which is where most of the cost "
                     f"comes from. {advice}"),
            project_id=pid, occurrences=len(items), est_tokens=tokens, est_usd=usd,
            evidence=_evidence(ds, [(t.session_id, t.turn_id) for t in items]),
            artifact=artifact,
        )


# --------------------------------------------------------------------------- file rereads

def file_rereads(ds: Dataset, min_sessions: int = 3) -> Iterator[Finding]:
    """Files read again in many sessions: summarize what Claude keeps looking up in CLAUDE.md."""
    reads: dict[tuple[int, str], list[Tool]] = defaultdict(list)
    for t in ds.tools:
        if t.name == "Read" and t.signature:
            reads[(ds.project_of(t.session_id), t.signature)].append(t)
    per_project: dict[int, list[tuple[str, list[Tool]]]] = defaultdict(list)
    for (pid, path), items in reads.items():
        if len({t.session_id for t in items}) >= min_sessions:
            per_project[pid].append((path, items))
    for pid, files in per_project.items():
        files.sort(key=lambda f: -len(f[1]))
        total_reads = sum(len(i) for _, i in files)
        sessions = {t.session_id for _, items in files for t in items}
        # Saving if half the re-reads become unnecessary: the read round trip + carrying its content.
        usd = sum(ds.sessions[t.session_id].cost_per_call + carry_cost(ds, t)
                  for _, items in files for t in items) * 0.5
        lines = "\n".join(f"- `{p}` — read {len(i)}× in {len({t.session_id for t in i})} sessions. "
                          "TODO: one line on what it contains / why it matters." for p, i in files[:15])
        yield Finding(
            type="file_rereads", key=str(pid),
            title=f"{len(files)} files re-read across {len(sessions)} sessions in {ds.project_name(pid)}",
            summary=(f"Claude opened these files {total_reads} times in separate sessions to rediscover the same "
                     "facts. A short 'key files' section in CLAUDE.md (what each holds, the conventions it defines) "
                     "lets it skip most of these reads."),
            project_id=pid, occurrences=total_reads, est_tokens=sum(t.result_tokens for _, i in files for t in i),
            est_usd=usd,
            evidence=_evidence(ds, [(t.session_id, t.turn_id) for _, items in files[:6] for t in items[:1]]),
            artifact=art.claude_md(f"## Key files\n\n{lines}"),
        )


# --------------------------------------------------------------------------- repeated prompts

def _words(text: str) -> set[str]:
    words = [w for w in re.findall(r"[a-zà-ÿ0-9]+", text.lower()) if w not in STOPWORDS and len(w) > 2]
    return set(words) | {f"{a} {b}" for a, b in itertools.pairwise(words)}


def repeated_prompts(ds: Dataset, threshold: float = 0.7, min_size: int = 3, max_findings: int = 5) -> Iterator[Finding]:
    """Near-identical prompts typed again and again -> a slash command with the instructions."""
    items = [(t, _words(t.prompt)) for t in sorted(ds.turns.values(), key=lambda t: t.ts)
             if len(t.prompt.split()) >= 5][-2000:]
    clusters: list[list[int]] = []
    rep: list[set[str]] = []
    for i, (_, w) in enumerate(items):
        if not w:
            continue
        for ci, r in enumerate(rep):
            inter = len(w & r)
            if inter and inter / len(w | r) >= threshold:
                clusters[ci].append(i)
                break
        else:
            clusters.append([i])
            rep.append(w)
    # Only near-identical wording counts: prompts that merely share a template ("refactor the X") don't.
    for members in sorted(clusters, key=len, reverse=True)[:max_findings]:
        if len(members) < min_size:
            continue
        turns = [items[i][0] for i in members]
        pid_counts = Counter(ds.project_of(t.session_id) for t in turns)
        pid = pid_counts.most_common(1)[0][0] if len(pid_counts) == 1 else None
        explore = sum(1 for tl in ds.tools if tl.turn_id in {t.id for t in turns} and tl.name in EXPLORATION_TOOLS)
        usd = explore * 0.5 * (sum(ds.sessions[t.session_id].cost_per_call for t in turns) / len(turns))
        common = Counter(w for t in turns for w in _words(t.prompt) if " " not in w)
        name = art.slug(" ".join(w for w, _ in common.most_common(3)), "repeat", 3)
        example = max(turns, key=lambda t: len(t.prompt)).prompt
        yield Finding(
            type="repeated_prompt", key=f"{pid}:{name}:{turns[0].id}",
            title=f"You asked for this {len(turns)} times: “{example[:70]}…”",
            summary=(f"{len(turns)} prompts with nearly the same wording, which triggered {explore} exploration calls "
                     "(Read/Grep/Glob). A slash command that carries the full instructions, plus the file locations "
                     "it needs, makes the request repeatable and skips most of the rediscovery."),
            project_id=pid, occurrences=len(turns), est_tokens=0, est_usd=usd,
            evidence=_evidence(ds, [(t.session_id, t.id) for t in turns]),
            artifact=art.slash_command(name, f"Reusable version of a prompt you typed {len(turns)} times", example),
        )


# --------------------------------------------------------------------------- model fit

def model_fit(ds: Dataset) -> Iterator[Finding]:
    """Exploration / chat / docs prompts run on the most expensive model tier."""
    per_project: dict[int, list] = defaultdict(list)
    for t in ds.turns.values():
        if not t.models or t.category not in CHEAP_CATEGORIES:
            continue
        expensive = {m: c for m, c in t.models.items() if EXPENSIVE_MODEL.search(m)}
        if not expensive:
            continue
        repriced = 0.0
        for m in expensive:
            u = t.by_model[m]
            repriced += cost_usd(FIT_TARGET_MODEL, u["input_tokens"], u["output_tokens"], u["cache_write_5m"],
                                 u["cache_write_1h"], u["cache_read"]) or 0.0
        saving = sum(expensive.values()) - repriced
        if saving > 0:
            per_project[ds.project_of(t.session_id)].append((t, saving))
    if price_for(FIT_TARGET_MODEL) is None:
        return
    for pid, rows in per_project.items():
        usd = sum(s for _, s in rows)
        cats = Counter(t.category for t, _ in rows)
        yield Finding(
            type="model_fit", key=str(pid),
            title=f"{len(rows)} {'/'.join(c for c, _ in cats.most_common(2))} prompts ran on a top-tier model "
                  f"in {ds.project_name(pid)}",
            summary=(f"These prompts mostly read code or answered questions. On {FIT_TARGET_MODEL} they would have "
                     f"cost about ${usd:.2f} less. Delegate exploration to a cheaper subagent, or switch with "
                     "`/model` for this kind of work."),
            project_id=pid, occurrences=len(rows), est_tokens=0, est_usd=usd,
            evidence=_evidence(ds, [(t.session_id, t.id) for t, _ in sorted(rows, key=lambda r: -r[1])]),
            artifact=art.subagent(
                "explorer", "Read-only codebase exploration: finding files, explaining how code works, answering "
                "questions about the repo. Use it before planning or editing.", "sonnet",
                ["Read", "Grep", "Glob"],
                "Explore the codebase to answer the question you are given. Report concrete file paths and line "
                "numbers, and keep the answer short. Never edit files."),
        )


# --------------------------------------------------------------------------- large contexts

def large_contexts(ds: Dataset) -> Iterator[Finding]:
    """Sessions whose every call re-reads a huge context: split tasks, /clear, /compact."""
    per_project: dict[int, list] = defaultdict(list)
    for s in ds.sessions.values():
        big = [(ts, m, ctx) for ts, m, ctx in s.contexts if ctx > LARGE_CONTEXT]
        if len(big) < 20:
            continue
        usd = 0.0
        for _, model, ctx in big:
            p = price_for(model)
            if p:
                usd += (ctx - TARGET_CONTEXT) * p.cache_read / 1_000_000
        per_project[s.project_id].append((s, len(big), usd * 0.5))
    for pid, rows in per_project.items():
        usd = sum(u for _, _, u in rows)
        calls = sum(n for _, n, _ in rows)
        worst = max(rows, key=lambda r: r[2])[0]
        yield Finding(
            type="large_context", key=str(pid),
            title=f"{calls:,} calls re-read a context over {LARGE_CONTEXT // 1000}k tokens in {ds.project_name(pid)}",
            summary=(f"{_n(len(rows), 'session')} kept growing past {LARGE_CONTEXT // 1000}k tokens. Every later call "
                     "re-reads all of it, so cache reads dominate the cost. Start a fresh session (or `/clear`) "
                     "between unrelated tasks and `/compact` long ones. The estimate assumes half the calls could "
                     f"run at ~{TARGET_CONTEXT // 1000}k."),
            project_id=pid, occurrences=calls, est_tokens=0, est_usd=usd,
            evidence=_evidence(ds, [(s.id, None) for s, _, _ in sorted(rows, key=lambda r: -r[2])]),
            artifact=art.tip(
                "- One task per session: `/clear` when you switch to something unrelated.\n"
                "- `/compact <what to keep>` before a long follow-up in the same task.\n"
                f"- Longest session here: “{worst.title or worst.id}”."),
        )


# --------------------------------------------------------------------------- cache rebuilds

def cache_rebuilds(ds: Dataset, min_usd: float = 0.5) -> Iterator[Finding]:
    per_project: dict[tuple[int, str], list] = defaultdict(list)
    for e in ds.rebuilds:
        if e.cause in ("idle_expired", "prefix_change", "model_switch"):
            per_project[(ds.project_of(e.session_id), e.cause)].append(e)
    advice = {
        "idle_expired": ("after the cache expired during a pause",
                         ("Coming back after a long break to a huge session rewrites the whole context. For a new "
                         "task, start a fresh session; for the same task, `/compact` first so the rewrite is small.")),
        "prefix_change": ("because the start of the prompt changed",
                          ("Something early in the context changed mid-session (CLAUDE.md, MCP tools, settings, "
                          "model options), invalidating the cache. Keep those stable during a session.")),
        "model_switch": ("after switching models",
                         ("Each model has its own cache, so switching mid-session rewrites the whole context. Pick the "
                         "model at the start, or delegate to a subagent instead of switching.")),
    }
    for (pid, cause), events in per_project.items():
        usd = sum(e.wasted_usd for e in events)
        if usd < min_usd:
            continue
        what, tip = advice[cause]
        yield Finding(
            type="cache_rebuild", key=f"{pid}:{cause}",
            title=f"{_n(len(events), 'cache rebuild')} {what} in {ds.project_name(pid)}",
            summary=(f"{sum(e.tokens for e in events):,} tokens were written to cache again instead of being read, "
                     f"about ${usd:.2f} extra. {tip}"),
            project_id=pid, occurrences=len(events), est_tokens=sum(e.tokens for e in events), est_usd=usd,
            evidence=_evidence(ds, [(e.session_id, None) for e in sorted(events, key=lambda e: -e.wasted_usd)]),
            artifact=art.tip(tip),
        )


MINERS = [allowlist, command_sequences, noisy_commands, fix_loops, context_bloat, file_rereads, repeated_prompts,
          model_fit, large_contexts, cache_rebuilds]
