"""FastAPI application factory. Run with `uvicorn --factory sliver_api.main:create_app`."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import Engine
from starlette.concurrency import run_in_threadpool

from .activity.log import ActivityLog
from .activity.routes import router as activity_router
from .auth.routes import router as auth_router
from .catalog.routes import router as catalog_router
from .config import Settings, get_settings
from .db import database_ready, make_engine, make_session_factory
from .payments.adapters import Facilitator, HttpFacilitator, Ledger, XrplLedger
from .payments.routes import router as payments_router
from .payments.service import PurchaseService
from .ratelimit import RateLimit, TokenBuckets
from .security import BodyLimit, OriginCheck
from .seller.routes import UPLOAD_BODY_LIMIT, UPLOAD_PATH
from .seller.routes import router as seller_router
from .storage import ObjectStore, S3Store

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    store: ObjectStore | None = None,
    facilitator: Facilitator | None = None,
    ledger: Ledger | None = None,
    rate_buckets: TokenBuckets | None = None,
) -> FastAPI:
    """Build the app. `engine`, `store`, `facilitator`, `ledger` and `rate_buckets` are seams for tests."""
    settings = settings or get_settings()
    engine = engine if engine is not None else make_engine(settings.database_url)
    store = store if store is not None else S3Store(settings)
    facilitator = facilitator if facilitator is not None else HttpFacilitator(settings.facilitator_url)
    ledger = ledger if ledger is not None else XrplLedger(settings.xrpl_rpc_url)

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
    app.state.purchases = PurchaseService(
        settings, store, facilitator, ledger, activity=ActivityLog(app.state.sessions)
    )

    app.include_router(catalog_router)
    app.include_router(payments_router)
    app.include_router(activity_router)
    app.include_router(auth_router)
    app.include_router(seller_router)
    # Added last runs first: rate limits, the Origin check, then body limits, then routing.
    app.add_middleware(BodyLimit, default_limit=64 * 1024, limits={UPLOAD_PATH: UPLOAD_BODY_LIMIT})
    app.add_middleware(OriginCheck, allowed_origins=settings.allowed_origins)
    if settings.sliver_rate_limit_enabled:
        app.add_middleware(
            RateLimit,
            config=settings.rate_limits,
            upload_path=UPLOAD_PATH,
            buckets=rate_buckets if rate_buckets is not None else TokenBuckets(),
        )

    @app.get("/api/health")
    def health() -> JSONResponse:
        storage_ready = store.ready()
        if not storage_ready:
            # A failed bucket bootstrap at startup heals on the next health probe.
            try:
                store.initialize()
                storage_ready = store.ready()
            except Exception:
                logger.warning("private storage still unavailable")
        checks = {
            "database": "ok" if database_ready(engine) else "unavailable",
            "storage": "ok" if storage_ready else "unavailable",
        }
        healthy = all(value == "ok" for value in checks.values())
        return JSONResponse(
            status_code=200 if healthy else 503,
            content={"status": "ok" if healthy else "degraded", "checks": checks},
        )

    return app
