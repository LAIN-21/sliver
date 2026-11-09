"""Public purchase activity: recent events, one purchase's timeline, and a live SSE stream."""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Path, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from starlette.concurrency import run_in_threadpool

from ..catalog.public import iso
from ..deps import DB
from ..models import ActivityEvent, Payment, Resource, utcnow
from .log import EVENT_TYPES
from .public import public_event

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["activity"])

MAX_EVENTS = 200
POLL_SECONDS = 0.5
HEARTBEAT_SECONDS = 15.0
# Streams end on their own so reloads and deploys never wait on them; EventSource reconnects
# with Last-Event-ID and misses nothing.
STREAM_SECONDS = 300.0
TYPE_PATTERN = "^(" + "|".join(EVENT_TYPES) + ")$"


def events_query():
    return select(ActivityEvent, Resource.title, Resource.status).outerjoin(
        Resource, ActivityEvent.resource_id == Resource.id
    )


def latest_id(db: Session) -> int:
    return db.scalar(select(func.max(ActivityEvent.id))) or 0


@router.get("/activity")
def activity(
    db: DB,
    limit: Annotated[int, Query(ge=1, le=MAX_EVENTS)] = 50,
    event_type: Annotated[str | None, Query(alias="type", pattern=TYPE_PATTERN)] = None,
) -> dict:
    """Most recent events first. `cursor` is the stream position to continue live from.

    The cursor is read before the items, so an event committed in between shows up twice (the
    client drops it by id) rather than never.
    """
    cursor = latest_id(db)
    query = events_query().order_by(ActivityEvent.id.desc()).limit(limit)
    if event_type:
        query = query.where(ActivityEvent.type == event_type)
    return {"items": [public_event(*row) for row in db.execute(query)], "cursor": cursor}


@router.get("/purchases/{payment_id}")
def purchase(payment_id: Annotated[str, Path(max_length=36)], db: DB) -> dict:
    """The timeline of one invoice, oldest step first; it also works after a reload."""
    events = [
        public_event(*row)
        for row in db.execute(
            events_query().where(ActivityEvent.payment_id == payment_id).order_by(ActivityEvent.id)
        )
    ]
    if not events:
        raise HTTPException(status_code=404, detail="Purchase not found.")
    payment = db.get(Payment, payment_id)
    if payment is None or (payment.status == "required" and payment.expires_at < utcnow()):
        status = "expired"  # unpaid invoices are purged once they expire
    else:
        status = payment.status
    with_tx = [event["transaction"] for event in events if event["transaction"]]
    validated = [event["transaction"] for event in events if event["type"] == "ledger_validated"]
    last = events[-1]
    return {
        "id": payment_id,
        "status": status,
        "failure_reason": payment.failure_reason if payment is not None else None,
        "expires_at": iso(payment.expires_at) if payment is not None else None,
        "resource": last["resource"],
        "amount": last["amount"],
        "network": last["network"],
        "pay_to": last["pay_to"],
        "payer": next((event["payer"] for event in reversed(events) if event["payer"]), None),
        "transaction": (validated or with_tx or [None])[-1],
        "agent_note": next((event["agent_note"] for event in reversed(events) if event["agent_note"]), None),
        "events": events,
    }


def read_after(sessions: sessionmaker[Session], cursor: int, payment_id: str | None) -> list[dict]:
    query = events_query().where(ActivityEvent.id > cursor).order_by(ActivityEvent.id).limit(MAX_EVENTS)
    if payment_id:
        query = query.where(ActivityEvent.payment_id == payment_id)
    with sessions() as db:
        return [public_event(*row) for row in db.execute(query)]


def sse(event: str, data: dict, event_id: int | None = None) -> str:
    head = f"id: {event_id}\n" if event_id is not None else ""
    return f"{head}event: {event}\ndata: {json.dumps(data, separators=(',', ':'))}\n\n"


async def event_stream(
    sessions: sessionmaker[Session],
    cursor: int,
    payment_id: str | None,
    is_disconnected: Callable[[], Awaitable[bool]],
    *,
    poll_seconds: float = POLL_SECONDS,
    heartbeat_seconds: float = HEARTBEAT_SECONDS,
    max_seconds: float = STREAM_SECONDS,
) -> AsyncIterator[str]:
    yield "retry: 2000\n\n"
    started = last_sent = time.monotonic()
    while time.monotonic() - started < max_seconds and not await is_disconnected():
        try:
            items = await run_in_threadpool(read_after, sessions, cursor, payment_id)
        except Exception:
            logger.warning("activity stream could not read events", exc_info=True)
            items = []
        for item in items:
            cursor = item["id"]
            yield sse("activity", item, cursor)
        now = time.monotonic()
        if items:
            last_sent = now
        elif now - last_sent >= heartbeat_seconds:
            last_sent = now
            yield sse("heartbeat", {"at": iso(utcnow()), "cursor": cursor})
        await asyncio.sleep(poll_seconds)


@router.get("/activity/stream")
async def activity_stream(
    request: Request,
    after: Annotated[int | None, Query(ge=0)] = None,
    payment_id: Annotated[str | None, Query(max_length=36)] = None,
    last_event_id: Annotated[str | None, Header(max_length=20)] = None,
) -> StreamingResponse:
    """Server-sent events: one `activity` event per new step, a `heartbeat` when quiet.

    Starts after `Last-Event-ID` (sent by EventSource on reconnect), else after `after`, else
    at the newest event. Pass `payment_id` to follow a single purchase.
    """
    sessions = request.app.state.sessions
    cursor = after
    if last_event_id and last_event_id.isdigit():
        cursor = int(last_event_id)
    if cursor is None:
        cursor = await run_in_threadpool(_latest, sessions)
    stream = event_stream(
        sessions,
        cursor,
        payment_id,
        request.is_disconnected,
        poll_seconds=POLL_SECONDS,
        heartbeat_seconds=HEARTBEAT_SECONDS,
        max_seconds=STREAM_SECONDS,
    )
    return StreamingResponse(
        stream,
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


def _latest(sessions: sessionmaker[Session]) -> int:
    with sessions() as db:
        return latest_id(db)
