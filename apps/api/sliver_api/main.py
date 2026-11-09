"""FastAPI application factory. Run with `uvicorn --factory sliver_api.main:create_app`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from starlette.concurrency import run_in_threadpool

from .config import Settings, get_settings
from .db import database_ready, make_engine, make_session_factory
from .storage import ObjectStore, S3Store

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    store: ObjectStore | None = None,
) -> FastAPI:
    """Build the app. `engine` and `store` are explicit seams for isolated tests."""
    settings = settings or get_settings()
    engine = engine if engine is not None else make_engine(settings.database_url)
    store = store if store is not None else S3Store(settings)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        try:
            await run_in_threadpool(store.initialize)
        except Exception:
            # Health reports storage as unavailable; the API itself stays up.
            logger.exception("private storage could not be initialized")
        yield
        engine.dispose()

    app = FastAPI(title="Sliver API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = make_session_factory(engine)
    app.state.store = store

    @app.get("/api/health")
    def health() -> JSONResponse:
        checks = {
            "database": "ok" if database_ready(engine) else "unavailable",
            "storage": "ok" if store.ready() else "unavailable",
        }
        healthy = all(value == "ok" for value in checks.values())
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ok" if healthy else "degraded", "checks": checks},
        )

    return app
