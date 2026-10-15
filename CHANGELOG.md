# Changelog

All notable changes are listed here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the project uses [Semantic Versioning](https://semver.org/).

## [0.1.0] - unreleased

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
