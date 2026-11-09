"""Shared fixtures: a dedicated PostgreSQL test database (created on demand) and an app factory."""

import os

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from sliver_api.config import Settings
from sliver_api.db import make_engine, make_session_factory
from sliver_api.main import create_app
from sliver_api.storage import MemoryStore

API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def resolve_test_database_url() -> str:
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("DATABASE_URL")
    if not base and os.environ.get("POSTGRES_HOST"):
        base = Settings().database_url  # built from POSTGRES_* inside the containers
    if not base:
        pytest.exit("Set DATABASE_URL or TEST_DATABASE_URL; run tests with `make test`.", returncode=2)
    url = make_url(base)
    return url.set(database=f"{url.database}_test").render_as_string(hide_password=False)


def ensure_database(url: str) -> None:
    target = make_url(url)
    admin = create_engine(target.set(database="postgres"), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as connection:
            exists = connection.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": target.database}
            ).scalar()
            if not exists:
                connection.execute(text(f'CREATE DATABASE "{target.database}"'))
    finally:
        admin.dispose()


@pytest.fixture(scope="session")
def database_url() -> str:
    url = resolve_test_database_url()
    ensure_database(url)
    config = Config(os.path.join(API_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(API_ROOT, "migrations"))
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    command.upgrade(config, "head")
    return url


@pytest.fixture
def settings(database_url) -> Settings:
    return Settings(
        database_url=database_url,
        s3_endpoint_url=os.environ.get("S3_ENDPOINT_URL", "http://127.0.0.1:9"),
        s3_access_key_id=os.environ.get("S3_ACCESS_KEY_ID", "test"),
        s3_secret_access_key=os.environ.get("S3_SECRET_ACCESS_KEY", "test"),
        s3_bucket=os.environ.get("TEST_S3_BUCKET", "sliver-test"),
    )


@pytest.fixture
def engine(settings):
    engine = make_engine(settings.database_url)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def clean_tables(database_url):
    yield
    engine = create_engine(database_url)
    try:
        with engine.begin() as connection:
            connection.execute(
                text("TRUNCATE activity_events, payments, search_events, resources, datasets, users CASCADE")
            )
    finally:
        engine.dispose()


@pytest.fixture
def sessions(engine):
    return make_session_factory(engine)


@pytest.fixture
def store() -> MemoryStore:
    return MemoryStore()


@pytest.fixture
def client(settings, engine, store):
    with TestClient(create_app(settings, engine=engine, store=store)) as test_client:
        yield test_client
