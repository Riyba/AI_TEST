"""Application settings, loaded from environment / .env."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Anthropic API key. If unset here, the SDK's normal env resolution applies.
    anthropic_api_key: str | None = None

    # Anthropic API base URL. Override to point at a proxy or compatible endpoint.
    anthropic_base_url: str = "https://api.anthropic.com"

    # Datadog API key for the metrics integration. Unset (the default)
    # disables the integration entirely — no Datadog network calls are made.
    datadog_api_key: str | None = None

    # Datadog site the account lives on (drives the intake hostname), e.g.
    # datadoghq.com, datadoghq.eu, us3.datadoghq.com, us5.datadoghq.com.
    datadog_site: str = "datadoghq.com"

    # Prefix for every submitted metric name.
    datadog_metric_prefix: str = "agent_studio"

    # Extra tags applied to every metric, comma-separated (e.g. "env:dev,team:me").
    datadog_tags: str = ""

    # Set to false to disable TLS certificate verification for Datadog rqeuests
    # (needed in environments with a self-signed corporate proxy certificate)
    datadog_ssl_verify: bool = True

    # GitHub token used by the github_create_pr tool (needs `pull_request:write`
    # on the target repo, e.g. a fine-grained PAT). Unset (the default) makes
    # the tool return a clear error instead of silently no-op'ing, since a
    # workflow node explicitly depends on it running.
    github_token: str | None = None

    # Optional colon-separated allowlist of directories that runs may target.
    # When set, a run's repo_path must resolve inside one of these. When empty
    # (the default), any existing directory is allowed — chosen via the file
    # browser in the UI.
    project_roots: str = ""

    # Where SQLite files live.
    data_dir: Path = Path("data")

    # Localhost only by design — do not change to 0.0.0.0.
    host: str = "127.0.0.1"
    port: int = 8000

    # Default max_tokens per LLM call.
    llm_max_tokens: int = 8192

    @property
    def db_path(self) -> Path:
        return self.data_dir / "app.db"

    @property
    def checkpoint_db_path(self) -> Path:
        return self.data_dir / "checkpoints.db"

    @property
    def db_url(self) -> str:
        return f"sqlite+aiosqlite:///{self.db_path}"

    @property
    def sync_db_url(self) -> str:
        return f"sqlite:///{self.db_path}"

    @property
    def datadog_enabled(self) -> bool:
        return bool(self.datadog_api_key)

    def datadog_base_tags(self) -> list[str]:
        return [t.strip() for t in self.datadog_tags.split(",") if t.strip()]

    def allowed_roots(self) -> list[Path]:
        return [
            Path(p).expanduser().resolve()
            for p in self.project_roots.split(":")
            if p.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings
