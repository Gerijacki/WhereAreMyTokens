"""Mask secrets and personal data before anything is stored or sent over the network.

Conservative by design: it is better to hide a harmless string than to keep a live key.
"""

from __future__ import annotations

import re

MASK = "[REDACTED]"

_PATTERNS: list[tuple[re.Pattern, str]] = [
    # Provider keys / tokens with recognizable prefixes
    (re.compile(r"\bsk-ant-[A-Za-z0-9_\-]{10,}"), MASK),
    (re.compile(r"\bsk-(proj-)?[A-Za-z0-9_\-]{20,}"), MASK),
    (re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})"), MASK),
    (re.compile(r"\b(AKIA|ASIA)[A-Z0-9]{16}\b"), MASK),
    (re.compile(r"\bAIza[0-9A-Za-z_\-]{35}\b"), MASK),
    (re.compile(r"\bxox[abprs]-[A-Za-z0-9-]{10,}"), MASK),
    (re.compile(r"\b(sk|rk|pk)_(live|test)_[A-Za-z0-9]{16,}"), MASK),
    (re.compile(r"\bnpm_[A-Za-z0-9]{30,}"), MASK),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"), MASK),  # JWT
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----", re.DOTALL), MASK),
    # Authorization headers
    (re.compile(r"(?i)\b(authorization\s*[:=]\s*)(bearer|basic|token)\s+[A-Za-z0-9._~+/=\-]{8,}"), rf"\1\2 {MASK}"),
    (re.compile(r"(?i)\b(bearer)\s+[A-Za-z0-9._~+/=\-]{20,}"), rf"\1 {MASK}"),
    # Credentials inside URLs: scheme://user:pass@host
    (re.compile(r"(\b[a-z][a-z0-9+.\-]*://[^/\s:@]+:)[^@\s/]+@"), rf"\1{MASK}@"),
    # KEY=value / "password": "value" style assignments of secret-looking names
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:SECRET|PASSWORD|PASSWD|PWD|TOKEN|API_?KEY|ACCESS_?KEY|PRIVATE_?KEY|"
                r"CLIENT_?SECRET|AUTH)[A-Z0-9_]*\s*[=:]\s*)(['\"]?)[^\s'\"&;]{4,}\2"), rf"\1\2{MASK}\2"),
    (re.compile(r"(?i)(--(?:password|token|api-key|secret)[= ])\S+"), rf"\1{MASK}"),
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"), "[EMAIL]"),
]


def redact(text: str | None) -> str | None:
    if not text:
        return text
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
