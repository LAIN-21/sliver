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
