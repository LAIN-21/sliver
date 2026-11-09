"""Typed runtime settings. Compose derives these from the repository `.env`."""

from functools import lru_cache

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    database_url: str
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str = Field(repr=False)
    s3_bucket: str = "sliver-private"
    s3_region: str = "us-east-1"
    worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    # Container-private path that the worker healthcheck in compose.yml reads.
    worker_heartbeat_path: str = "/tmp/sliver-worker.heartbeat"  # noqa: S108

    @field_validator("database_url")
    @classmethod
    def postgres_only(cls, value: str) -> str:
        # ADR 0001: PostgreSQL is the primary database; there is no SQLite runtime mode.
        if not value.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use postgresql+psycopg://")
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
