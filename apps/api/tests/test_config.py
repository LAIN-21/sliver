import pytest
from pydantic import ValidationError

from sliver_api.config import Settings

BASE = {
    "s3_endpoint_url": "http://127.0.0.1:9000",
    "s3_access_key_id": "key",
    "s3_secret_access_key": "secret",
}


def test_rejects_non_postgres_database():
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite:///sliver.db", **BASE)


def test_secret_is_not_in_repr():
    settings = Settings(database_url="postgresql+psycopg://u:p@db/sliver", **BASE)
    assert "secret" not in repr(settings)


def test_builds_database_url_from_parts_with_escaped_credentials():
    from sqlalchemy.engine import make_url

    settings = Settings(
        postgres_host="postgres",
        postgres_user="sliver",
        postgres_password="pass@word:/#",
        postgres_db="sliver",
        **BASE,
    )
    url = make_url(settings.database_url)
    assert (url.host, url.username, url.database) == ("postgres", "sliver", "sliver")
    assert url.password == "pass@word:/#"


def test_explicit_database_url_takes_precedence():
    explicit = "postgresql+psycopg://other:secret@db.internal/sliver"
    settings = Settings(
        database_url=explicit, postgres_host="postgres", postgres_user="x", postgres_db="y", **BASE
    )
    assert settings.database_url == explicit


def test_requires_database_url_or_parts(monkeypatch):
    for name in ("DATABASE_URL", "POSTGRES_HOST", "POSTGRES_USER", "POSTGRES_DB"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ValidationError):
        Settings(**BASE)
