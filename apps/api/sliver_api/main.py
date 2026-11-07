"""Local seller API. Protected bytes never enter catalog serialization."""

import hashlib
import hmac
import ipaddress
import logging
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Annotated, Literal

from fastapi import Body, Depends, FastAPI, File, Form, HTTPException, Query, Request, Response, UploadFile
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from sqlalchemy import create_engine, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings
from .csv_validation import MAX_FILE_BYTES, InvalidCSV, inspect_csv
from .models import Dataset, LoginSession, Quote, Resource, User, identifier, utcnow
from .payments import valid_classic_address, verify_testnet_payment
from .security import hash_password, token_hash, verify_password
from .storage import ObjectStore, S3Store

logger = logging.getLogger(__name__)
COOKIE = "sliver_session"


def fail(status: int, code: str, message: str):
    raise HTTPException(status_code=status, detail={"code": code, "message": message})


class BodyLimitMiddleware:
    """Reject oversized bodies before the multipart parser can spool them to disk."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] not in {"POST", "PUT", "PATCH"}:
            return await self.app(scope, receive, send)
        limit = MAX_FILE_BYTES + 65_536 if scope["path"] == "/api/datasets" else 65_536
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            body = message.get("body", b"")
            size += len(body)
            if size > limit:
                response = JSONResponse(status_code=413, content={"detail": {
                    "code": "request_too_large", "message": "Request exceeds the upload limit."
                }})
                return await response(scope, receive, send)
            chunks.append(body)
            if not message.get("more_body", False):
                break
        sent = False

        async def replay():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


class InputModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    @field_validator("*", mode="before")
    @classmethod
    def reject_nul(cls, value):
        # PostgreSQL text cannot contain U+0000; reject before any persistence.
        if isinstance(value, str) and "\0" in value:
            raise ValueError("Text fields must not contain NUL characters.")
        return value


class LoginInput(InputModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)

    @field_validator("email")
    @classmethod
    def normalized_email(cls, value):
        return value.strip().lower()


class Provenance(InputModel):
    source: str = Field(min_length=1, max_length=500)
    method: str = Field(min_length=1, max_length=500)
    collected_at: str = Field(min_length=1, max_length=40)
    coverage: str = Field(min_length=1, max_length=500)
    rights_statement: str = Field(min_length=1, max_length=2000)

    @field_validator("collected_at")
    @classmethod
    def valid_date(cls, value):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            raise ValueError("Use an ISO 8601 collection date or timestamp.") from None
        # Python accepts compact/week dates that JavaScript Date cannot parse.
        # Persist one interoperable UTC representation rather than the raw input.
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class ResourceInput(InputModel):
    dataset_id: str = Field(min_length=1, max_length=36)
    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1, max_length=2000)
    price_minor: Annotated[StrictInt, Field(gt=0, le=100_000_000)]
    currency: Literal["USD"]


class ReviewInput(InputModel):
    decision: Literal["approve", "reject"]
    reason: str = Field(min_length=1, max_length=2000)


class QuoteInput(InputModel):
    resource_id: str = Field(min_length=1, max_length=36)
    buyer_address: str | None = Field(default=None, min_length=25, max_length=35)

    @field_validator("buyer_address")
    @classmethod
    def classic_address(cls, value):
        if value is not None and not valid_classic_address(value):
            raise ValueError("Use a valid classic XRPL account address.")
        return value


class ConfirmInput(InputModel):
    transaction_hash: str | None = Field(default=None, pattern=r"^[A-Fa-f0-9]{64}$")

    @field_validator("transaction_hash")
    @classmethod
    def normalized_hash(cls, value):
        return value.upper() if value else None


def iso(value):
    return value.isoformat(timespec="seconds") + "Z" if value else None


def user_json(user):
    return {"id": user.id, "email": user.email, "role": user.role} if user else None


def dataset_json(dataset):
    return {"id": dataset.id, "owner_id": dataset.owner_id, "title": dataset.title,
            "filename": dataset.filename, "version": 1, "sha256": dataset.sha256,
            "size_bytes": dataset.size_bytes, "row_count": dataset.row_count,
            "columns": dataset.columns, "created_at": iso(dataset.created_at),
            "provenance": dataset.provenance,
            "validation": {"valid": True, "warnings": dataset.warnings}}


def resource_json(resource):
    return {"id": resource.id, "dataset_id": resource.dataset_id, "dataset_version": 1,
            "owner_id": resource.owner_id, "title": resource.title,
            "description": resource.description, "price_minor": resource.price_minor,
            "currency": resource.currency, "status": resource.status,
            "review_reason": resource.review_reason, "created_at": iso(resource.created_at)}


def quote_json(quote):
    return {"id": quote.id, "resource_id": quote.resource_id, "title": quote.title,
            "dataset_version": quote.dataset_version, "sha256": quote.sha256,
            "size_bytes": quote.size_bytes, "price_minor": quote.price_minor,
            "currency": quote.currency, "mode": quote.mode, "network": quote.network,
            "amount_drops": quote.amount_drops, "pay_to": quote.pay_to,
            "buyer_address": quote.buyer_address, "memo": quote.id,
            "expires_at": iso(quote.expires_at), "status": quote.status,
            "transaction_hash": quote.transaction_hash, "receipt_id": quote.receipt_id,
            "paid_at": iso(quote.paid_at),
            "download_url": f"/api/quotes/{quote.id}/download" if quote.status == "paid" else None}


def create_app(settings: Settings, *, engine=None, store: ObjectStore | None = None) -> FastAPI:
    """The alternate engine/store parameters are explicit isolated-test seams."""
    engine = engine if engine is not None else create_engine(settings.database_url, pool_pre_ping=True)
    store = store if store is not None else S3Store(settings)
    sessions = sessionmaker(engine, expire_on_commit=False)
    api = FastAPI(title="Sliver seller API", version="0.1.0")
    api.add_middleware(BodyLimitMiddleware)
    api.state.engine, api.state.store = engine, store
    # A fixed valid dummy hash avoids a materially cheaper unknown-account response.
    dummy_hash = hash_password(secrets.token_urlsafe(32))

    @api.exception_handler(RequestValidationError)
    async def validation_error(_request, _error):
        return JSONResponse(status_code=422, content={"detail": {
            "code": "invalid_input", "message": "Check required fields, allowed values and input limits."
        }})

    @api.middleware("http")
    async def private_cache_headers(request, call_next):
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    def db_session():
        with sessions() as db:
            yield db

    DB = Annotated[Session, Depends(db_session)]

    def current_session(request: Request, db: Session):
        raw = request.cookies.get(COOKIE)
        session = db.get(LoginSession, token_hash(raw)) if raw else None
        if session and session.expires_at <= utcnow():
            db.delete(session)
            db.commit()
            return None
        return session

    def require_user(request: Request, db: Session, role=None):
        session = current_session(request, db)
        user = db.get(User, session.user_id) if session and session.user_id else None
        if not user:
            fail(401, "authentication_required", "Log in to continue.")
        if role and user.role != role:
            fail(403, "role_required", f"This action requires a {role} account.")
        return user

    def csrf(request: Request, db: Session):
        origin = request.headers.get("origin", "")
        if origin not in settings.allowed_origins:
            fail(403, "origin_denied", "Request origin is not allowed.")
        session = current_session(request, db)
        supplied = request.headers.get("x-csrf-token", "")
        valid_format = len(supplied) == 64 and all(char in "0123456789abcdef" for char in supplied)
        if not session or not valid_format or not hmac.compare_digest(session.csrf_token, supplied):
            fail(403, "csrf_failed", "Refresh your session and try again.")
        return session

    def new_session(db: Session, response: Response, user_id=None):
        raw = secrets.token_urlsafe(32)
        session = LoginSession(token_hash=token_hash(raw), csrf_token=secrets.token_hex(32),
                               user_id=user_id,
                               expires_at=utcnow() + timedelta(seconds=settings.session_ttl_seconds))
        db.add(session)
        db.commit()
        response.set_cookie(COOKIE, raw, httponly=True, secure=settings.session_secure,
                            samesite="strict", max_age=settings.session_ttl_seconds, path="/")
        return session

    def private_dataset(db, dataset_id, user):
        if "\0" in dataset_id:
            fail(422, "invalid_input", "Identifiers must not contain NUL characters.")
        dataset = db.get(Dataset, dataset_id)
        if not dataset or (user.role != "reviewer" and dataset.owner_id != user.id):
            fail(404, "not_found", "Dataset not found.")
        return dataset

    def private_resource(db, resource_id, user):
        if "\0" in resource_id:
            fail(422, "invalid_input", "Identifiers must not contain NUL characters.")
        resource = db.get(Resource, resource_id)
        if not resource or (user.role != "reviewer" and resource.owner_id != user.id):
            fail(404, "not_found", "Resource not found.")
        return resource

    @api.get("/api/health")
    def health():
        return {"status": "ok", "mode": "local-demo"}

    @api.get("/api/session")
    def get_session(request: Request, response: Response, db: DB):
        session = current_session(request, db) or new_session(db, response)
        user = db.get(User, session.user_id) if session.user_id else None
        return {"user": user_json(user), "csrf_token": session.csrf_token}

    @api.post("/api/session")
    def login(body: LoginInput, request: Request, response: Response, db: DB):
        old_session = csrf(request, db)
        user = db.scalar(select(User).where(User.email == body.email.lower()))
        if not verify_password(body.password, user.password_hash if user else dummy_hash) or not user:
            fail(401, "invalid_credentials", "Email or password is incorrect.")
        db.delete(old_session)
        new = new_session(db, response, user.id)
        return {"user": user_json(user), "csrf_token": new.csrf_token}

    @api.delete("/api/session", status_code=204)
    def logout(request: Request, response: Response, db: DB):
        session = csrf(request, db)
        db.delete(session)
        db.commit()
        response.delete_cookie(COOKIE, path="/", secure=settings.session_secure,
                               httponly=True, samesite="strict")

    @api.get("/api/datasets")
    def list_datasets(request: Request, db: DB):
        user = require_user(request, db)
        query = select(Dataset).order_by(Dataset.created_at.desc())
        if user.role != "reviewer":
            query = query.where(Dataset.owner_id == user.id)
        return {"items": [dataset_json(d) for d in db.scalars(query)]}

    @api.post("/api/datasets", status_code=201)
    async def upload_dataset(request: Request, db: DB, file: UploadFile = File(),
                             title: str = Form(), provenance: str = Form()):
        csrf(request, db)
        user = require_user(request, db, "seller")
        title = title.strip()
        if "\0" in title or "\0" in (file.filename or ""):
            fail(422, "invalid_input", "Text fields must not contain NUL characters.")
        if not title or len(title) > 160:
            fail(422, "invalid_title", "Title must contain between 1 and 160 characters.")
        try:
            declaration = Provenance.model_validate_json(provenance).model_dump()
        except ValueError:
            fail(422, "invalid_input", "Provide valid source, method, ISO collection date, coverage and a rights declaration.")
        try:
            data = await file.read(MAX_FILE_BYTES + 1)
        finally:
            await file.close()
        try:
            inspection = inspect_csv(data)
        except InvalidCSV as error:
            raise HTTPException(status_code=422, detail={"code": "invalid_csv",
                                "message": str(error), "issues": [error.issue]}) from None
        dataset_id = identifier()
        key = f"datasets/{dataset_id}/v1.csv"
        filename = PurePosixPath((file.filename or "dataset.csv").replace("\\", "/")).name[:200]
        dataset = Dataset(id=dataset_id, owner_id=user.id, title=title,
                          filename=filename or "dataset.csv", object_key=key,
                          sha256=hashlib.sha256(data).hexdigest(), size_bytes=len(data),
                          row_count=inspection["row_count"], columns=inspection["columns"],
                          provenance=declaration, warnings=inspection["warnings"])
        try:
            store.put(key, data)
        except Exception:
            logger.exception("Private object upload failed")
            fail(503, "storage_unavailable", "Private storage is unavailable. Try again later.")
        try:
            db.add(dataset)
            db.commit()
        except Exception:
            db.rollback()
            try:
                store.delete(key)
            except Exception:
                logger.exception("Could not clean up unreferenced private object")
            raise
        return dataset_json(dataset)

    @api.get("/api/datasets/{dataset_id}")
    def get_dataset(dataset_id: str, request: Request, db: DB):
        return dataset_json(private_dataset(db, dataset_id, require_user(request, db)))

    def read_bytes(dataset):
        try:
            data = store.get(dataset.object_key)
            if len(data) != dataset.size_bytes or hashlib.sha256(data).hexdigest() != dataset.sha256:
                raise ValueError("Stored content no longer matches the immutable upload digest")
            return data
        except Exception:
            logger.exception("Private object retrieval failed")
            fail(503, "storage_unavailable", "Private file is unavailable or failed its integrity check.")

    @api.get("/api/datasets/{dataset_id}/preview")
    def preview_dataset(dataset_id: str, request: Request, db: DB):
        dataset = private_dataset(db, dataset_id, require_user(request, db))
        inspection = inspect_csv(read_bytes(dataset))
        return {"columns": inspection["columns"], "rows": inspection["preview"],
                "truncated": dataset.row_count > len(inspection["preview"])}

    @api.get("/api/datasets/{dataset_id}/download")
    def download_dataset(dataset_id: str, request: Request, db: DB):
        dataset = private_dataset(db, dataset_id, require_user(request, db))
        return Response(content=read_bytes(dataset), media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="dataset-{dataset.id}.csv"'})

    @api.get("/api/resources")
    def list_resources(request: Request, db: DB):
        user = require_user(request, db)
        query = select(Resource).order_by(Resource.created_at.desc())
        if user.role != "reviewer":
            query = query.where(Resource.owner_id == user.id)
        return {"items": [resource_json(r) for r in db.scalars(query)]}

    @api.post("/api/resources", status_code=201)
    def create_resource(body: ResourceInput, request: Request, db: DB):
        csrf(request, db)
        user = require_user(request, db, "seller")
        private_dataset(db, body.dataset_id, user)
        resource = Resource(**body.model_dump(), owner_id=user.id)
        db.add(resource)
        db.commit()
        return resource_json(resource)

    @api.post("/api/resources/{resource_id}/submit")
    def submit_resource(resource_id: str, request: Request, db: DB):
        csrf(request, db)
        user = require_user(request, db, "seller")
        resource = private_resource(db, resource_id, user)
        result = db.execute(update(Resource).where(Resource.id == resource.id, Resource.status == "draft")
                            .values(status="submitted"))
        if result.rowcount != 1:
            fail(409, "invalid_state", "Only draft Resources can be submitted.")
        db.commit()
        db.refresh(resource)
        return resource_json(resource)

    @api.post("/api/resources/{resource_id}/review")
    def review_resource(resource_id: str, body: ReviewInput, request: Request, db: DB):
        csrf(request, db)
        require_user(request, db, "reviewer")
        if "\0" in resource_id:
            fail(422, "invalid_input", "Identifiers must not contain NUL characters.")
        resource = db.get(Resource, resource_id)
        if not resource:
            fail(404, "not_found", "Resource not found.")
        approved = body.decision == "approve"
        result = db.execute(update(Resource).where(Resource.id == resource_id, Resource.status == "submitted")
                            .values(status="approved" if approved else "rejected",
                                    review_reason=body.reason, approved_at=utcnow() if approved else None))
        if result.rowcount != 1:
            fail(409, "invalid_state", "Only submitted Resources can be reviewed.")
        db.commit()
        db.refresh(resource)
        return resource_json(resource)

    @api.get("/api/catalog")
    def catalog(db: DB, q: Annotated[str, Query(max_length=200)] = "",
                max_price_minor: Annotated[int | None, Query(ge=0, le=100_000_000)] = None,
                limit: Annotated[int, Query(ge=1, le=100)] = 50,
                offset: Annotated[int, Query(ge=0, le=1_000_000)] = 0):
        if "\0" in q:
            fail(422, "invalid_input", "Search must not contain NUL characters.")
        query = select(Resource, Dataset).join(Dataset, Resource.dataset_id == Dataset.id).where(
            Resource.status == "approved")
        if q.strip():
            # contains(autoescape) treats wildcard characters as literal input.
            query = query.where(or_(func.lower(Resource.title).contains(q.strip().lower(), autoescape=True),
                                    func.lower(Resource.description).contains(q.strip().lower(), autoescape=True)))
        if max_price_minor is not None:
            query = query.where(Resource.price_minor <= max_price_minor)
        total = db.scalar(select(func.count()).select_from(query.subquery()))
        rows = db.execute(query.order_by(Resource.approved_at.desc(), Resource.id).offset(offset).limit(limit))
        return {"total": total, "items": [{"id": r.id, "title": r.title, "description": r.description,
                           "price_minor": r.price_minor, "currency": r.currency,
                           "sha256": d.sha256, "size_bytes": d.size_bytes,
                           "dataset_version": 1, "row_count": d.row_count, "columns": d.columns,
                           "provenance": {key: d.provenance[key] for key in
                                          ("source", "method", "collected_at", "coverage")},
                           "approved_at": iso(r.approved_at)} for r, d in rows]}

    def payment_available(request: Request, mode=None):
        if settings.payment_mode == "disabled":
            fail(503, "payments_disabled", "Payment confirmation is disabled in this server configuration.")
        if mode and mode != settings.payment_mode:
            fail(409, "payment_mode_changed", "This quote belongs to a different payment mode. Create a new quote.")
        if settings.payment_mode == "simulated":
            try:
                local = request.client and ipaddress.ip_address(request.client.host).is_loopback
            except ValueError:
                local = False
            if not local:
                fail(403, "simulation_local_only", "Simulated purchases are available only over loopback.")

    def owned_quote(quote_id, request, db):
        if "\0" in quote_id or len(quote_id) > 36:
            fail(404, "not_found", "Quote not found.")
        session = current_session(request, db)
        quote = db.get(Quote, quote_id) if session else None
        if not quote or quote.owner_session_hash != session.token_hash:
            fail(404, "not_found", "Quote not found.")
        return quote

    @api.get("/api/marketplace")
    def marketplace():
        mode = settings.payment_mode
        return {"mode": mode, "network": "simulation" if mode == "simulated" else
                ("xrpl:1" if mode == "xrpl-testnet" else None),
                "quote_ttl_seconds": settings.quote_ttl_seconds,
                "price_note": "SIMULATED / NO REAL MONEY" if mode == "simulated" else
                ("XRPL TESTNET ONLY. Illustrative conversion; no live FX: "
                 f"{settings.testnet_drops_per_usd} testnet drops per USD." if mode == "xrpl-testnet"
                 else "Payments are disabled."),
                "capabilities": {"quotes": mode != "disabled", "simulated_confirmation": mode == "simulated",
                                 "testnet_verification": mode == "xrpl-testnet", "server_signing": False}}

    @api.post("/api/quotes", status_code=201)
    def create_quote(body: QuoteInput, request: Request, db: DB):
        session = csrf(request, db)
        payment_available(request)
        if settings.payment_mode == "xrpl-testnet" and body.buyer_address is None:
            fail(422, "buyer_address_required", "A classic buyer account address is required for testnet verification.")
        row = db.execute(select(Resource, Dataset).join(Dataset, Resource.dataset_id == Dataset.id)
                         .where(Resource.id == body.resource_id, Resource.status == "approved")).first()
        if not row:
            fail(404, "not_found", "Approved Resource not found.")
        resource, dataset = row
        real = settings.payment_mode == "xrpl-testnet"
        quote = Quote(owner_session_hash=session.token_hash, resource_id=resource.id, dataset_id=dataset.id,
                      dataset_version=1, object_key=dataset.object_key, title=resource.title,
                      sha256=dataset.sha256, size_bytes=dataset.size_bytes, price_minor=resource.price_minor,
                      currency=resource.currency, mode=settings.payment_mode,
                      network="xrpl:1" if real else "simulation",
                      amount_drops=str((resource.price_minor * settings.testnet_drops_per_usd + 99) // 100) if real else None,
                      pay_to=settings.xrpl_pay_to if real else None, buyer_address=body.buyer_address,
                      expires_at=utcnow() + timedelta(seconds=settings.quote_ttl_seconds))
        db.add(quote)
        db.commit()
        return quote_json(quote)

    @api.get("/api/quotes/{quote_id}")
    def get_quote(quote_id: str, request: Request, db: DB):
        return quote_json(owned_quote(quote_id, request, db))

    @api.post("/api/quotes/{quote_id}/confirm")
    def confirm_quote(quote_id: str, request: Request, response: Response, db: DB,
                      body: ConfirmInput = Body(default=ConfirmInput())):
        csrf(request, db)
        quote = owned_quote(quote_id, request, db)
        payment_available(request, quote.mode)
        if quote.mode == "simulated" and body.transaction_hash:
            fail(422, "simulation_no_transaction", "Simulation accepts no ledger transaction hash.")
        if quote.mode == "xrpl-testnet" and not body.transaction_hash:
            fail(422, "transaction_hash_required", "Provide the 64-character testnet transaction hash.")
        if quote.transaction_hash and quote.transaction_hash != body.transaction_hash:
            fail(409, "payment_attempt_locked", "Reconcile the original transaction hash; do not send another payment.")
        if quote.status == "paid":
            return quote_json(quote)
        if quote.status == "failed":
            fail(409, "payment_failed", "This payment proof failed verification. No purchase was granted.")
        now = utcnow()
        if quote.mode == "simulated":
            db.execute(update(Quote).where(Quote.id == quote.id, Quote.status == "quoted", Quote.expires_at > now)
                       .values(status="paid", receipt_id="SIM-" + quote.id, paid_at=now))
            db.commit()
            db.refresh(quote)
            if quote.status != "paid":
                fail(410, "quote_expired", "This quote expired. Create a new quote before confirming.")
            return quote_json(quote)
        if quote.status == "quoted":
            # Record the immutable attempt before I/O, but do not globally reserve
            # unverified public hashes: another quote may be their rightful payee.
            db.execute(update(Quote).where(Quote.id == quote.id, Quote.status == "quoted", Quote.expires_at > now)
                       .values(status="pending", transaction_hash=body.transaction_hash))
            db.commit()
            db.refresh(quote)
        if quote.status == "quoted":
            fail(410, "quote_expired", "This quote expired before a payment attempt was recorded.")
        if quote.transaction_hash != body.transaction_hash:
            fail(409, "payment_attempt_locked", "Reconcile the original transaction hash; do not send another payment.")
        # End the read transaction before slow RPC I/O; updates below are conditional.
        db.commit()
        outcome = verify_testnet_payment(quote, settings.xrpl_rpc_url)
        if outcome in {"paid", "failed"}:
            values = {"status": outcome}
            if outcome == "paid":
                values.update(receipt_id="TESTNET-" + quote.id, paid_at=utcnow(),
                              settled_transaction_hash=body.transaction_hash)
            try:
                # Only verified settlement claims the globally unique proof. The
                # uniqueness constraint and state transition commit atomically.
                db.execute(update(Quote).where(Quote.id == quote.id, Quote.status == "pending",
                                              Quote.transaction_hash == body.transaction_hash).values(**values))
                db.commit()
            except IntegrityError:
                db.rollback()
                fail(409, "payment_proof_used", "This verified transaction already settled another quote.")
        db.refresh(quote)
        if quote.status == "failed":
            fail(422, "invalid_payment_proof", "The validated transaction did not meet this quote's payment requirements.")
        if quote.status == "pending":
            response.status_code = 202
        return quote_json(quote)

    @api.get("/api/quotes/{quote_id}/download")
    def purchase_download(quote_id: str, request: Request, db: DB):
        quote = owned_quote(quote_id, request, db)
        if quote.status != "paid":
            raise HTTPException(status_code=402, detail={"code": "payment_required",
                                "message": "Confirm this quote before downloading its private bytes.",
                                "requirements": quote_json(quote)})
        if quote.dataset_version != 1:
            fail(409, "version_unavailable", "The purchased immutable version is unavailable.")
        return Response(content=read_bytes(quote), media_type="application/octet-stream",
                        headers={"Content-Disposition": f'attachment; filename="purchase-{quote.id}.csv"',
                                 "X-Content-SHA256": quote.sha256})

    return api


def production_app():
    return create_app(Settings.from_env())


# Uvicorn's --factory form is also supported; this lazy wrapper avoids connecting
# to PostgreSQL/S3 when tests import create_app.
class LazyApplication:
    def __init__(self):
        self.application = None

    async def __call__(self, scope, receive, send):
        if self.application is None:
            self.application = production_app()
        await self.application(scope, receive, send)


app = LazyApplication()
