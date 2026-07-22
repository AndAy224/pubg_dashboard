"""Application settings, loaded from the repo-root `.env`."""

from __future__ import annotations

import pathlib
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# backend/pubg_dashboard/config.py -> repo root
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

Shard = Literal["steam", "xbox", "psn", "kakao", "console"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- PUBG API -----------------------------------------------------------
    pubg_api_key: str = ""
    pubg_default_shard: Shard = "steam"
    pubg_rate_limit_per_min: int = 10
    poll_interval_seconds: int = 300
    pubg_seed_players: Annotated[list[str], NoDecode] = Field(default_factory=list)

    # --- Database -----------------------------------------------------------
    database_url: str = "postgresql+asyncpg://pubg:pubg@localhost:5432/pubg"

    # --- Storage ------------------------------------------------------------
    storage_backend: Literal["minio", "filesystem"] = "minio"
    minio_endpoint: str = "http://localhost:9000"
    minio_root_user: str = "pubgadmin"
    minio_root_password: str = ""
    minio_bucket: str = "pubg-telemetry"
    telemetry_dir: pathlib.Path = REPO_ROOT / "data" / "telemetry"

    # --- Retention ----------------------------------------------------------
    raw_telemetry_retention_days: int = 0

    # --- App ----------------------------------------------------------------
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    cors_origins: Annotated[list[str], NoDecode] = Field(
        default_factory=lambda: ["http://localhost:5173"]
    )

    # ------------------------------------------------------------------------
    # `.env` holds comma-separated strings. `NoDecode` on the annotations above
    # is load-bearing: without it the dotenv source JSON-decodes any `list[str]`
    # field *before* validators run, so the documented
    # `PUBG_SEED_PLAYERS=AndAy,DaddyGainz,SIERIUS_` raised a SettingsError at
    # import time and nothing in the app could start. `NoDecode` hands the raw
    # string through to this validator instead.
    @field_validator("pubg_seed_players", "cors_origins", mode="before")
    @classmethod
    def _split_csv(cls, v: object) -> object:
        if isinstance(v, str):
            return [part.strip() for part in v.split(",") if part.strip()]
        return v

    # `.env` ships `TELEMETRY_DIR=./data/telemetry`, which would otherwise
    # resolve against the *current working directory*. The CLI runs from
    # `backend/`, the worker from wherever systemd puts it, and tests from the
    # repo root — so the same setting pointed at three different places and the
    # importer silently reported every match's telemetry as "missing" rather
    # than failing. Anchor relative paths to the repo root.
    @field_validator("telemetry_dir", mode="after")
    @classmethod
    def _anchor_to_repo_root(cls, v: pathlib.Path) -> pathlib.Path:
        return v if v.is_absolute() else (REPO_ROOT / v).resolve()

    @property
    def match_archive_dir(self) -> pathlib.Path:
        """Where `scripts/panic_archive.py` parked raw match JSON."""
        return REPO_ROOT / "data" / "matches"


@lru_cache
def get_settings() -> Settings:
    return Settings()
