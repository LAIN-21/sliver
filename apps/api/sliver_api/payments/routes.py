from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select

from ..activity.log import sanitize_note
from ..deps import DB
from ..models import Payment, Resource, User
from .service import Challenge, PurchaseError, PurchaseService
from .x402 import drops_for, encode_header, explorer_url

router = APIRouter(tags=["payments"])


@router.get("/api/resources/{resource_id}/data", response_model=None)
def resource_data(resource_id: Annotated[str, Path(max_length=36)], request: Request, db: DB) -> Response:
    """Pay-per-request CSV delivery gated by x402 v2 on the XRP Ledger (HTTP 402).

    Optional `X-Sliver-Agent-Note`: the buying agent's reason, shown publicly on the activity
    feed (UTF-8, at most 200 characters after sanitizing). It never affects the payment.
    """
    service: PurchaseService = request.app.state.purchases
    note = sanitize_note(request.headers.get("X-Sliver-Agent-Note"))
    try:
        outcome = service.handle(
            db, resource_id, request.headers.get("PAYMENT-SIGNATURE"), str(request.url), agent_note=note
        )
    except PurchaseError as error:
        return JSONResponse(
            status_code=error.status, content={"error": {"code": error.code, "message": error.message}}
        )
    if isinstance(outcome, Challenge):
        return JSONResponse(
            status_code=402, content=outcome.body, headers={"PAYMENT-REQUIRED": encode_header(outcome.body)}
        )
    return Response(
        content=outcome.data,
        media_type="text/csv",
        headers={
            "PAYMENT-RESPONSE": encode_header(outcome.settlement),
            "X-Sliver-Receipt": outcome.payment.id,
            "Content-Disposition": f'attachment; filename="sliver-{resource_id}.csv"',
            "Cache-Control": "no-store",
        },
    )


@router.get("/api/receipts/{payment_id}")
def receipt(payment_id: Annotated[str, Path(max_length=36)], db: DB) -> dict:
    row = db.execute(
        select(Payment, Resource.title)
        .join(Resource, Payment.resource_id == Resource.id)
        .where(Payment.id == payment_id, Payment.status == "delivered")
    ).first()
    if row is None:
        raise HTTPException(status_code=404, detail="Receipt not found.")
    payment, title = row
    return {
        "id": payment.id,
        "resource": {"id": payment.resource_id, "title": title},
        "amount": {"value": payment.amount, "asset": payment.asset, "usd_minor": payment.price_minor},
        "network": payment.network,
        "pay_to": payment.pay_to,
        "payer": payment.payer,
        "transaction": {
            "hash": payment.tx_hash,
            "ledger_index": payment.ledger_index,
            "explorer_url": explorer_url(payment.tx_hash),
        },
        "settled_at": payment.settled_at.isoformat().replace("+00:00", "Z") if payment.settled_at else None,
    }


@router.get("/.well-known/x402")
def x402_directory(request: Request, db: DB) -> dict:
    """Machine-readable list of paid endpoints, for agents and x402 directories."""
    settings = request.app.state.settings
    base = str(request.base_url).rstrip("/")
    rows = db.execute(
        select(Resource)
        .join(User, Resource.owner_id == User.id)
        .where(Resource.status == "published", User.xrpl_address.is_not(None))
        .order_by(Resource.published_at.desc())
        .limit(200)
    ).scalars()
    return {
        "x402Version": 2,
        "items": [
            {
                "url": f"{base}/api/resources/{resource.id}/data",
                "name": resource.title,
                "description": resource.description,
                "category": resource.category,
                "mimeType": "text/csv",
                "price": {
                    "scheme": "exact",
                    "network": settings.xrpl_network,
                    "asset": "XRP",
                    "amount": drops_for(resource.price_minor, settings.drops_per_usd),
                    "usdMinor": resource.price_minor,
                },
            }
            for resource in rows
        ],
    }
