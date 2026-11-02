"""Explicit local application configuration; infrastructure remains in Compose."""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


@dataclass(frozen=True)
class Settings:
    database_url: str
    s3_endpoint_url: str = "http://127.0.0.1:9000"
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    s3_bucket: str = "sliver-private"
    s3_region: str = "us-east-1"
    session_secure: bool = False
    session_ttl_seconds: int = 28_800
    allowed_origins: tuple[str, ...] = (
        "http://127.0.0.1:5173", "http://localhost:5173"
    )

    @classmethod
    def from_env(cls) -> "Settings":
        load_dotenv(Path(__file__).resolve().parents[3] / ".env", override=False)
        database_url = os.environ.get("DATABASE_URL", "")
        if not database_url:
            raise RuntimeError("Set DATABASE_URL in the repository .env before starting the API.")
        if not database_url.startswith("postgresql+psycopg://"):
            raise RuntimeError("The application requires PostgreSQL via postgresql+psycopg://.")
        ttl = int(os.environ.get("SESSION_TTL_SECONDS", "28800"))
        if not 300 <= ttl <= 86_400:
            raise RuntimeError("SESSION_TTL_SECONDS must be between 300 and 86400.")
        origins = tuple(x.strip() for x in os.environ.get(
            "SLIVER_ALLOWED_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173"
        ).split(",") if x.strip())
        if not origins or "*" in origins:
            raise RuntimeError("Configure explicit SLIVER_ALLOWED_ORIGINS; wildcard is forbidden.")
        return cls(
            database_url=database_url,
            s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:9000"),
            s3_access_key_id=os.environ.get("S3_ACCESS_KEY_ID", ""),
            s3_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY", ""),
            s3_bucket=os.environ.get("S3_BUCKET", "sliver-private"),
            s3_region=os.environ.get("S3_REGION", "us-east-1"),
            session_secure=os.environ.get("SESSION_SECURE", "false").lower() == "true",
            session_ttl_seconds=ttl,
            allowed_origins=origins,
        )
