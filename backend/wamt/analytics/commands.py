"""Normalize tool targets so that repeated actions can be counted.

Claude Code rarely runs a bare command: it's `cd "<project>" && pnpm build 2>&1 | tail -n 5`.
A *signature* keeps only what identifies the action ("pnpm build"), dropping directory
changes, env assignments, output filters and arguments.
"""

from __future__ import annotations

import re
import shlex
from pathlib import PurePosixPath

# Programs whose first argument is a subcommand worth keeping (git status vs git push).
_SUBCOMMAND = {
    "git", "npm", "pnpm", "yarn", "bun", "npx", "docker", "docker-compose", "kubectl", "helm", "go",
    "cargo", "uv", "pip", "pip3", "poetry", "composer", "dotnet", "make", "terraform", "gh", "brew",
    "apt", "apt-get", "php", "deno", "mvn", "gradle", "flutter", "rails", "bundle", "rake", "wamt",
}
# ... and those where the second level matters too (gh run list, docker compose up, pnpm exec vitest).
_TWO_LEVEL = {("gh", None), ("docker", "compose"), ("pnpm", "exec"), ("pnpm", "dlx"), ("npm", "run"),
              ("pnpm", "run"), ("yarn", "run"), ("uv", "run"), ("php", "artisan"), ("python", "-m"), ("python3", "-m"),
              ("npx", None), ("go", "test"), ("cargo", "run")}
# Segments that never identify an action on their own.
_NOISE = {"cd", "pushd", "popd", "export", "set", "unset", "echo", "printf", "true", "false", "sleep",
          "source", ".", "wait", "clear", "exit", ":"}
# When reached through a pipe these only filter output.
_FILTERS = {"tail", "head", "grep", "rg", "sed", "awk", "sort", "uniq", "wc", "cut", "tr", "less", "more",
            "cat", "tee", "jq", "column", "xargs", "findstr", "select-object", "out-null", "select-string"}
_ENV_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
_KEYWORDS = {"for", "while", "until", "if", "elif", "case", "esac", "done", "fi", "function", "{", "}", "(", ")"}
_KEYWORD_PREFIX = {"do", "then", "else", "!"}
_INTERPRETERS = {"python", "python3", "py", "node", "bash", "sh", "zsh", "pwsh", "powershell", "deno", "tsx",
                 "ts-node", "ruby", "perl"}
_HEREDOC = re.compile(r"<<-?\s*(['\"]?)(\w+)\1[^\n]*\n.*?\n\s*\2\b", re.DOTALL)
_WORD = re.compile(r"^[A-Za-z][\w:.-]*$")  # a subcommand, not a path / url / value
_SUBST = re.compile(r"\$\([^()]*\)|`[^`]*`")


def split_segments(cmd: str) -> list[tuple[str, str]]:
    """Split a shell line into (separator_before, segment), respecting quotes.

    Separators: '' (start), '&&', '||', ';', '|', '\\n'.
    """
    out: list[tuple[str, str]] = []
    buf: list[str] = []
    sep = ""
    quote: str | None = None
    i = 0
    n = len(cmd)
    while i < n:
        c = cmd[i]
        if quote:
            buf.append(c)
            if c == quote:
                quote = None
            elif c == "\\" and quote == '"' and i + 1 < n:
                buf.append(cmd[i + 1])
                i += 1
        elif c in "'\"":
            quote = c
            buf.append(c)
        elif c == "\\" and i + 1 < n and cmd[i + 1] == "\n":
            i += 1  # line continuation
        elif cmd.startswith("&&", i) or cmd.startswith("||", i):
            out.append((sep, "".join(buf).strip()))
            buf, sep = [], cmd[i:i + 2]
            i += 1
        elif c in ";\n" or (c == "|" and not cmd.startswith("|&", i)):
            out.append((sep, "".join(buf).strip()))
            buf, sep = [], ("|" if c == "|" else c.replace("\n", ";"))
        elif c == "&" and i + 1 < n and cmd[i + 1] == ">":
            buf.append(c)  # &> redirect
        else:
            buf.append(c)
        i += 1
    out.append((sep, "".join(buf).strip()))
    return [(s, seg) for s, seg in out if seg]


def _tokens(segment: str) -> list[str]:
    try:
        toks = shlex.split(segment, posix=True)
    except ValueError:
        toks = segment.split()
    return [t for t in toks if t]


def _program(tok: str) -> str:
    name = tok.replace("\\", "/").rsplit("/", 1)[-1].lower()
    for ext in (".exe", ".cmd", ".bat", ".ps1", ".sh"):
        name = name.removesuffix(ext)
    return name


def segment_signature(segment: str) -> str | None:
    toks = _tokens(segment)
    while toks and _ENV_ASSIGN.match(toks[0]):
        toks = toks[1:]
    # Drop redirections like 2>&1, >/dev/null
    toks = [t for t in toks if not re.match(r"^\d*[<>]", t)]
    while toks and toks[0] in _KEYWORD_PREFIX:  # `do cat x` -> `cat x`
        toks = toks[1:]
    if not toks or toks[0] in _KEYWORDS:
        return None
    prog = _program(toks[0])
    if prog in _NOISE:
        return None
    if prog in _INTERPRETERS and any(t in ("-e", "-c", "--eval", "-Command") for t in toks[1:3]):
        return f"{prog} (inline script)"
    if prog in ("sudo", "time", "nohup", "exec", "env") and len(toks) > 1:
        return segment_signature(" ".join(shlex.quote(t) for t in toks[1:]))
    args = [t for t in toks[1:] if not t.startswith("-") or t == "-m"]
    if args and args[0] == "HEREDOC":
        return f"{prog} (inline script)"
    if prog in _SUBCOMMAND or (prog, "-m") in _TWO_LEVEL:
        if not args or not _WORD.match(args[0]):
            return prog
        sub = args[0]
        if (prog, None) in _TWO_LEVEL or (prog, sub) in _TWO_LEVEL:
            rest = [a for a in args[1:] if not a.startswith("-")]
            return f"{prog} {sub} {rest[0]}" if rest and _WORD.match(rest[0]) else f"{prog} {sub}"
        return f"{prog} {sub}"
    if prog in _INTERPRETERS:
        script = next((a for a in args if not a.startswith("-")), None)
        return f"{prog} {PurePosixPath(script.replace(chr(92), '/')).name}" if script else prog
    return prog


def command_signature(cmd: str | None, max_parts: int = 3) -> str | None:
    """'cd "x" && pnpm build 2>&1 | tail -n 5 && pnpm test' -> 'pnpm build && pnpm test'."""
    if not cmd:
        return None
    cmd = _HEREDOC.sub("HEREDOC", cmd)
    for _ in range(3):  # nested $( ) substitutions, innermost first
        cmd = _SUBST.sub("SUBST", cmd)
    parts: list[str] = []
    for sep, seg in split_segments(cmd):
        if sep == "|" and _program((_tokens(seg) or [""])[0]) in _FILTERS:
            continue
        sig = segment_signature(seg)
        if sig and (not parts or parts[-1] != sig):
            parts.append(sig)
    if not parts:
        return None
    return " && ".join(parts[:max_parts]) + (" && …" if len(parts) > max_parts else "")


def normalize_path(path: str | None, project_root: str | None = None) -> str | None:
    """Project-relative, forward-slash, case-folded drive: c:\\X\\a.ts and C:/X/a.ts compare equal."""
    if not path:
        return None
    p = path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:/", p):
        p = p[0].lower() + p[1:]
    elif re.match(r"^/[a-zA-Z]/", p):  # Git Bash style /c/Users/...
        p = f"{p[1].lower()}:{p[2:]}"
    if project_root:
        root = normalize_path(project_root).rstrip("/") + "/"
        if p.lower().startswith(root.lower()):
            return p[len(root):]
    return p


SHELL_TOOLS = {"Bash", "PowerShell"}
FILE_TOOLS = {"Read", "Edit", "Write", "MultiEdit", "NotebookEdit"}


def tool_signature(name: str, target: str | None, project_root: str | None) -> str | None:
    if name in SHELL_TOOLS:
        return command_signature(target)
    if name in FILE_TOOLS:
        return normalize_path(target, project_root)
    if name in ("Grep", "Glob"):
        return (target or "")[:200] or None
    if name in ("WebFetch",):
        m = re.match(r"https?://([^/]+)", target or "")
        return m.group(1) if m else None
    return None


def allowlist_rule(signature: str) -> str:
    """Claude Code permission rule for a single-command signature (prefix match)."""
    return f"Bash({signature}:*)"
