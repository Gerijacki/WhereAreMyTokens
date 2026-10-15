# Security policy

WhereAreMyTokens processes Claude Code transcripts, which can contain source code, prompts and secrets. We treat privacy issues as security issues.

## Reporting a vulnerability

Please **don't open a public issue**. Report it privately through GitHub: **Security → Report a vulnerability** on this repository. Include steps to reproduce and the affected version or commit. You'll get an acknowledgement within a few days.

Examples of what's in scope:

- data from transcripts leaking outside the configured database, agent or alert channel;
- secrets surviving redaction (`backend/wamt/collector/redact.py`);
- auth bypass for the dashboard, `/api/ingest`, `/v1/*` or `/metrics`;
- injection or path traversal through transcript content or API input.

## Hardening checklist for self-hosters

- Keep the transcript mount **read-only** (the default in `docker-compose.yml`).
- Set `WAMT_AUTH_PASSWORD`, or put the app behind an authenticating reverse proxy, before exposing it beyond localhost. Use TLS.
- Change `POSTGRES_PASSWORD`, and don't publish the Postgres port.
- Give each agent machine its own device token, and revoke tokens you no longer use (`wamt device revoke`).
- Use `WAMT_STORE_PROMPTS=false` if prompts are too sensitive to store at all.
