"""Background worker for seller pipeline jobs.

Jobs will live in PostgreSQL and be claimed with `FOR UPDATE SKIP LOCKED` (ADR 0003), so no
queue service is needed. Until pipeline stages exist, the loop only proves database access and
writes a heartbeat file that the container healthcheck reads.
"""

import logging
import signal
import threading
from pathlib import Path

from .config import Settings, get_settings
from .db import database_ready, make_engine

logger = logging.getLogger("sliver_api.worker")


def run_once(settings: Settings, engine) -> bool:
    ready = database_ready(engine)
    if ready:
        Path(settings.worker_heartbeat_path).touch()
    else:
        logger.warning("database unavailable; heartbeat not written")
    return ready


def run(settings: Settings, stop: threading.Event) -> None:
    engine = make_engine(settings.database_url)
    logger.info("worker started")
    try:
        while not stop.is_set():
            run_once(settings, engine)
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
