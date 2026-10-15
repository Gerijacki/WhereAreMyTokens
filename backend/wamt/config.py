from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="WAMT_", env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./wamt.db"
    # Directory containing Claude Code transcripts (~/.claude/projects), mounted read-only in Docker.
    claude_data_dir: Path = Path.home() / ".claude" / "projects"
    # Name of the machine the transcripts come from (multi-device support later on).
    source_name: str = "local"
    # Seconds between incremental scans. Polling (not inotify) because file events
    # don't propagate through Docker bind mounts on Windows/macOS.
    scan_interval: float = 5.0
    ingest_enabled: bool = True
    # Optional override of the bundled pricing table.
    pricing_file: Path | None = None
    # Timezone used to bucket daily charts.
    timezone: str = "UTC"
    static_dir: Path | None = None

    # Privacy
    store_prompts: bool = True  # False: keep only prompt length, never the text
    redact_secrets: bool = True  # mask API keys, tokens, passwords, emails in prompts and commands

    # Dashboard auth. Unset password = open (fine on localhost / behind an authenticating proxy).
    auth_password: str | None = None
    trust_proxy_auth_header: str | None = None  # e.g. "Remote-User" set by Authelia/oauth2-proxy
    secret_key: str | None = None  # signs session cookies; generated and stored in the DB if unset
    session_days: int = 30
    metrics_token: str | None = None  # protects /metrics when set

    # Alerts
    alert_url: str | None = None  # ntfy topic URL, Discord/Slack webhook, or any JSON webhook
    alert_block_factor: float = 1.5  # alert when the 5h block is projected above factor x median block
    alert_digest_hour: int | None = None  # local hour (0-23) for a daily digest; unset = off
    public_url: str | None = None  # used for links inside alerts


@lru_cache
def get_settings() -> Settings:
    return Settings()
