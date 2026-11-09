import json
from typing import Annotated

from fastapi import APIRouter, Path, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError

from ..catalog.public import public_quote
from ..deps import DB
from ..models import User
from ..payments.x402 import drops_for
from . import custom

router = APIRouter(tags=["custom slices"])

NO_STORE = {"Cache-Control": "no-store"}


def refusal(status: int, code: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message, **extra}}, headers=NO_STORE
    )


def parse_where(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        value = None
    if not isinstance(value, dict) or not all(isinstance(item, str) for item in value.values()):
        raise custom.Refused(
            422, "invalid_where", 'where must be a JSON object such as {"lane": "SGSIN-CNSHA"}.'
        )
    return value


@router.get("/api/resources/{resource_id}/slices", response_model=None)
def quote_custom_slice(
    resource_id: Annotated[str, Path(max_length=36)],
    request: Request,
    db: DB,
    time_start: Annotated[str | None, Query(max_length=10)] = None,
    time_end: Annotated[str | None, Query(max_length=10)] = None,
    where: Annotated[str | None, Query(max_length=1000, description="JSON object: column -> value")] = None,
) -> JSONResponse:
    """Quote a buyer-defined custom slice of a published full-dataset listing (#39). Never spends.

    The filter is a time range on the dataset's time column (`time_start`, `time_end`: YYYY,
    YYYY-MM or YYYY-MM-DD, inclusive) and/or equality on category columns (`where`, a JSON object).
    The answer is an unlisted, published Resource: its id, rows, coverage, price with breakdown
    and SHA-256. Buy it with `GET /api/resources/{id}/data` (x402). Identical requests return the
    same Resource. A GET, not a POST: agents send no browser Origin, the endpoint uses no cookies,
    and the result is deterministic, so repeating it changes nothing. Quotes have their own
    per-IP budget (`SLIVER_RATE_LIMIT_SLICE_QUOTE_PER_MINUTE`, sliver_api/ratelimit.py).
    """
    store = request.app.state.store
    for attempt in range(2):
        try:
            resource, parent, created = custom.quote(
                db, store, resource_id, time_start=time_start, time_end=time_end, where=parse_where(where)
            )
            seller = db.get(User, resource.owner_id)
            seller_name = seller.display_name if seller else ""
            breakdown = custom.price_breakdown(resource)
            settings = request.app.state.settings
            payment = {
                "network": settings.xrpl_network,
                "asset": "XRP",
                "amount_drops": drops_for(resource.price_minor, settings.drops_per_usd),
                "drops_per_usd": settings.drops_per_usd,
            }
            validity = {
                # The slice and its price never change while the parent listing stays published.
                "expires_at": None,
                "price_fixed": True,
                # Each purchase attempt gets a fresh x402 invoice that must be paid within this.
                "invoice_timeout_seconds": settings.payment_timeout_seconds,
            }
            body = public_quote(resource, parent, seller_name, breakdown, created, payment, validity)
            db.commit()
        except custom.Refused as error:
            db.rollback()
            return refusal(error.status, error.code, error.message, **error.extra)
        except IntegrityError:
            # Another process created the same slice between our check and insert: read it back.
            db.rollback()
            if attempt:
                raise
            continue
        return JSONResponse(status_code=201 if created else 200, content=body, headers=NO_STORE)
    raise AssertionError("unreachable")
