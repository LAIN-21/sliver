import os

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

API_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_migrations_reach_head(database_url):
    engine = create_engine(database_url)
    try:
        with engine.connect() as connection:
            version = connection.execute(text("SELECT version_num FROM alembic_version")).scalar()
    finally:
        engine.dispose()
    config = Config(os.path.join(API_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(API_ROOT, "migrations"))
    from alembic.script import ScriptDirectory

    assert version == ScriptDirectory.from_config(config).get_current_head()


def test_downgrade_and_upgrade_round_trip(database_url):
    config = Config(os.path.join(API_ROOT, "alembic.ini"))
    config.set_main_option("script_location", os.path.join(API_ROOT, "migrations"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.downgrade(config, "base")
    command.upgrade(config, "head")
