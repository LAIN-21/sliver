import os
import time

from sliver_api.db import make_engine
from sliver_api.worker import run_once


def test_heartbeat_written_when_database_is_reachable(settings, engine, tmp_path):
    heartbeat = tmp_path / "heartbeat"
    settings = settings.model_copy(update={"worker_heartbeat_path": str(heartbeat)})
    assert run_once(settings, engine)
    assert time.time() - os.path.getmtime(heartbeat) < 5


def test_no_heartbeat_when_database_is_unreachable(settings, tmp_path):
    heartbeat = tmp_path / "heartbeat"
    settings = settings.model_copy(update={"worker_heartbeat_path": str(heartbeat)})
    unreachable = make_engine("postgresql+psycopg://sliver:wrong@127.0.0.1:9/none")
    assert not run_once(settings, unreachable)
    assert not heartbeat.exists()
