# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [Unreleased]

### Added

- Filter by device: every view that filters by project also takes a device (`?device=`), with a selector, a Device column in Sessions and a *By device* card on the Overview once a second machine sends data. `GET /api/sources` lists the devices, and session exports have a `device` column.
- `wamt agent` keeps records it can't send yet in a local queue (`spool/` next to its state file) and sends them when the server is reachable again, so a long time offline loses nothing even after Claude Code deletes old transcripts.
- `deploy/wamt-agent.service`, a systemd user service for the agent, and [docs/homelab.md](docs/homelab.md), a guide to one server with several computers.

## [0.3.1] - 2026-10-16

### Added

- `docker run ghcr.io/gerijacki/wherearemytokens demo`: try it in one command on synthetic data, without cloning.
- The image runs standalone with SQLite in `/data/wamt` (a volume) when `WAMT_DATABASE_URL` isn't set. Before, it failed to start without PostgreSQL.
- `make screenshots` regenerates the README screenshots and the demo GIF from demo data.

### Changed

- The dashboard is built once, natively, for both image architectures, instead of under arm64 emulation. Releases build faster and can't hang there; the release job also times out after 30 minutes.
- The image has an entrypoint: `serve` (default), `demo`, or any command such as `wamt agent`.

## [0.3.0] - 2026-10-16

> **Heads-up:** amounts are now shown in **euros by default**. To keep dollars, switch to USD in *Settings* or set `WAMT_CURRENCY=USD`. Set your exchange rate there too (`WAMT_EUR_PER_USD`, default 0.86): WAMT never looks it up online. Stored data is unchanged; the API still serves USD.

### Added

- **Settings page**: theme, currency and exchange rate, plan and billing, dashboard password, devices and exports, in one place. Environment variables still win, and lock the matching field.
- **Themes**: light, dark or system, from the header or Settings, remembered per browser and applied before the first paint.
- **Dashboard password from the UI**, stored as a salted scrypt hash. Changing or removing it signs every other browser out. A *Log out* button appears when a password is set.
- **Euros**: every amount can be shown in EUR (the new default) or USD, at a rate you set (`WAMT_CURRENCY`, `WAMT_EUR_PER_USD`). The API keeps serving USD.
- **Plan prices per currency and billing period**: Pro €18/$20 monthly or €15/$17 annual, Max 5x €90/$100, Max 20x €180/$200 (`WAMT_BILLING`).
- **Devices in the UI**: create agent tokens (shown once, with the `wamt agent` command to run) and revoke them.
- **Exports**: `/api/export/{sessions|prompts|daily}.{csv|json}`, from Settings or the Sessions page.

### Changed

- The plan chosen in *Plan value* is saved on the server instead of in the browser.
- Text, number and password fields share the dashboard's input style, with visible focus and disabled states.
- The `plans` section of `pricing.yaml` lists `prices` per currency and billing period. Custom files with the 0.2 `usd_month` format still work.

## [0.2.0] - 2026-10-16

### Added

- **Plan value**: the last 30 days at API prices against each subscription plan's price, plus a monthly chart. Plan prices live in the new `plans` section of `pricing.yaml`; `WAMT_PLAN` preselects yours.
- **Budgets**: daily, weekly or monthly limits on API-equivalent spend, overall or per project, with a projection to the end of the period and alerts at 80% and 100%.
- **Realized savings**: insights marked done are measured again after a week, and show what the fix actually saved, adjusted for how much you used Claude Code since.
- End-to-end tests with Playwright against the real backend on demo data, unit tests for the dashboard with Vitest, and a CI job for both.
- A `Makefile` for local development on Linux and macOS.

### Changed

- The *Done* insights tab also lists insights whose pattern is no longer detected, since that's what a successful fix looks like.

### Migrations

- `0003` adds the `budgets` table and the realized-savings columns of `insights`.

## [0.1.0] - 2026-10-15

### Added

**Collection**
- Incremental, read-only ingestion of Claude Code transcripts.
- Deduplication of API responses by message id.
- Attribution of every API call, including subagent calls, to the prompt that caused it.

**Analytics and dashboards**
- API-equivalent cost per model and token kind (5-minute and 1-hour cache writes, cache reads), from an editable `pricing.yaml`.
- Dashboards: Overview, Activity (work categories, 5-hour blocks, burn rate, heatmap, weekly cost), Tools, Cache, Sessions and Session detail.
- Rule-based work categorization (English/Catalan/Spanish), with manual overrides.
- Cache rebuild detection with causes: idle past the TTL, compaction, model switch, prompt prefix change.

**Insights**
- Ten insight detectors with estimated savings and ready-to-paste fixes: skills, slash commands, subagents, hooks, `settings.json` permissions and `CLAUDE.md` sections.

**Self-hosting**
- `wamt agent` with device tokens, so several machines can feed one server. Records are slimmed and redacted before they leave the machine.
- Privacy controls: secret and email redaction, and an option to never store prompt text.
- Optional password or reverse-proxy authentication.
- ntfy/Discord/Slack/webhook alerts.
- Prometheus `/metrics` and an OpenTelemetry (OTLP/JSON) receiver.
- Alembic migrations, including upgrades of databases created before migrations existed.
- `wamt demo` synthetic data and `docker-compose.demo.yml`.
