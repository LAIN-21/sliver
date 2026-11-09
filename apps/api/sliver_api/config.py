"""Typed runtime settings. Compose derives these from the repository `.env`."""

from functools import lru_cache

from pydantic import Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    model_config = SettingsConfigDict(extra="ignore")

    # Either an explicit DATABASE_URL, or the POSTGRES_* parts it is built from.
    database_url: str = ""
    postgres_host: str = ""
    postgres_port: int = 5432
    postgres_user: str = ""
    postgres_password: str = Field(default="", repr=False)
    postgres_db: str = ""
    s3_endpoint_url: str
    s3_access_key_id: str
    s3_secret_access_key: str = Field(repr=False)
    s3_bucket: str = "sliver-private"
    s3_region: str = "us-east-1"
    worker_poll_seconds: float = Field(default=2.0, gt=0, le=60)
    # Container-private path that the worker healthcheck in compose.yml reads.
    worker_heartbeat_path: str = "/tmp/sliver-worker.heartbeat"  # noqa: S108

    @model_validator(mode="after")
    def build_database_url(self) -> "Settings":
        if not self.database_url:
            if not (self.postgres_host and self.postgres_user and self.postgres_db):
                raise ValueError("Set DATABASE_URL, or POSTGRES_HOST, POSTGRES_USER and POSTGRES_DB")
            # URL.create escapes credentials, so passwords such as "pass@word" stay intact.
            self.database_url = URL.create(
                "postgresql+psycopg",
                username=self.postgres_user,
                password=self.postgres_password or None,
                host=self.postgres_host,
                port=self.postgres_port,
                database=self.postgres_db,
            ).render_as_string(hide_password=False)
        return self.postgres_only()

    def postgres_only(self) -> "Settings":
        # ADR 0001: PostgreSQL is the primary database; there is no SQLite runtime mode.
        if not self.database_url.startswith("postgresql+psycopg://"):
            raise ValueError("DATABASE_URL must use postgresql+psycopg://")
        return self

    @field_validator("database_url")
    @classmethod
    def strip(cls, value: str) -> str:
        return value.strip()


@lru_cache
def get_settings() -> Settings:
    return Settings()
