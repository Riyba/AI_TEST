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

    # Colon-separated list of directories that runs are allowed to target.
    # A run's repo_path must resolve inside one of these. Required for running
    # workflows; CRUD works without it.
    project_roots: str = ""

    # Where SQLite files live.
    data_dir: Path = Path("data")

    # Localhost only by design — do not change to 0.0.0.0.
    host: str = "127.0.0.1"
    port: int = 8000

    # Hard cap on agent tool-use loop iterations per node.
    max_tool_iterations: int = 10
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
