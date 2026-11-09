"""Background worker for seller pipeline jobs.

Jobs are `pipeline_steps` rows in PostgreSQL claimed with `FOR UPDATE SKIP LOCKED` (ADR 0003),
so no queue service is needed. Each loop writes a heartbeat file that the container healthcheck
reads, then runs every claimable step.
"""

import logging
import signal
import threading
from pathlib import Path

from .config import Settings, get_settings
from .db import database_ready, make_engine, make_session_factory
from .pipeline.jobs import process_available
from .storage import ObjectStore, S3Store

logger = logging.getLogger("sliver_api.worker")


def run_once(settings: Settings, engine) -> bool:
    ready = database_ready(engine)
    if ready:
        Path(settings.worker_heartbeat_path).touch()
    else:
        logger.warning("database unavailable; heartbeat not written")
    return ready


def work(settings: Settings, engine, store: ObjectStore) -> int:
    """One loop iteration: heartbeat, then drain the claimable pipeline steps."""
    if not run_once(settings, engine):
        return 0
    try:
        # A small batch keeps the heartbeat fresh while a long queue drains.
        return process_available(
            make_session_factory(engine), store, settings.pipeline_step_timeout_seconds, limit=10
        )
    except Exception:
        logger.exception("pipeline iteration failed")
        return 0


def run(settings: Settings, stop: threading.Event) -> None:
    engine = make_engine(settings.database_url)
    store = S3Store(settings)
    logger.info("worker started")
    try:
        while not stop.is_set():
            if not work(settings, engine, store):
                stop.wait(settings.worker_poll_seconds)
    finally:
        engine.dispose()
        logger.info("worker stopped")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    stop = threading.Event()
    for signum in (signal.SIGTERM, signal.SIGINT):
        signal.signal(signum, lambda *_: stop.set())
    run(get_settings(), stop)


if __name__ == "__main__":
    main()
