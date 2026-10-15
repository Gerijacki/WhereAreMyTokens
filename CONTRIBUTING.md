# Contributing

Thanks for helping make Claude Code usage easier to understand. Bug reports, insight ideas, pricing updates and pull requests are all welcome.

## Ground rules

- **Never commit real transcripts, prompts or tokens.** Tests and screenshots use synthetic data: `wamt demo` or the fixtures in `backend/tests/fixtures`. CI runs a secret scan on every push.
- Keep the backend working on **both SQLite and PostgreSQL**.
- Schema changes go through Alembic: `backend/wamt/migrations/versions/`.
- Every insight must state how its saving is estimated.

## Setup

```bash
cd backend
python -m venv .venv && .venv/bin/pip install -e ".[dev]"     # Windows: .venv\Scripts\
.venv/bin/pytest -q
.venv/bin/ruff check wamt tests

cd ../web
pnpm install
pnpm build          # type-checks too
pnpm dev            # http://localhost:5173, proxies /api to :8787
```

To get realistic data without your own, run `wamt demo --dir /tmp/demo` and then `WAMT_CLAUDE_DATA_DIR=/tmp/demo wamt serve`.

## Common changes

| You want to… | Edit |
|---|---|
| Update model prices | `backend/wamt/pricing/pricing.yaml`. Add the source link in the PR. |
| Improve categorization | `backend/wamt/analytics/rules.yaml`, plus a case in `tests/test_analytics.py` |
| Handle a new transcript format quirk | `backend/wamt/collector/parser.py`, plus a test, and bump `PARSER_VERSION` in `ingest.py` |
| Add an insight detector | A generator in `backend/wamt/insights/miners.py` added to `MINERS`, a planted pattern in `wamt/demo.py`, and a test |
| Add a migration | `alembic revision --autogenerate` against a database at head (see `wamt/migrations/env.py`) |

## Pull requests

- Keep PRs focused and describe the user-visible change.
- `pytest`, `ruff` and `pnpm build` must pass. CI also smoke-tests the Docker image on demo data.
- For UI changes, add a screenshot taken from **demo data**.
