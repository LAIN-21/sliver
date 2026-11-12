"""The current seller agreement and its recorded acceptances."""

import hashlib
import json
from pathlib import Path
from typing import Annotated

from fastapi import Depends, HTTPException
from pydantic import BaseModel, Field, StrictBool
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from ..auth.deps import CurrentSeller
from ..deps import DB
from ..models import SellerAgreementAcceptance, User, utcnow

# Publish a new file for a new agreement. Keep the released files for the acceptance record.
CURRENT_VERSION = "demo-v1"


def document() -> dict:
    path = Path(__file__).with_name("agreements") / f"{CURRENT_VERSION}.json"
    content = json.loads(path.read_text(encoding="utf-8"))
    canonical = json.dumps(content, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return {**content, "version": CURRENT_VERSION, "content_sha256": digest}


CURRENT_DOCUMENT = document()


class AgreementDecision(BaseModel):
    version: str = Field(min_length=1, max_length=32)
    content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    accepted: StrictBool


def acceptance(db: Session, seller: User) -> SellerAgreementAcceptance | None:
    return db.get(
        SellerAgreementAcceptance,
        (seller.id, CURRENT_DOCUMENT["version"], CURRENT_DOCUMENT["content_sha256"]),
    )


def agreement_status(db: Session, seller: User) -> dict:
    record = acceptance(db, seller)
    return {**CURRENT_DOCUMENT, "accepted_at": record.accepted_at if record else None}


def accept_agreement(db: Session, seller: User, form: AgreementDecision) -> dict:
    if not form.accepted:
        raise HTTPException(status_code=422, detail="Confirm that you agree before continuing.")
    if (
        form.version != CURRENT_DOCUMENT["version"]
        or form.content_sha256 != CURRENT_DOCUMENT["content_sha256"]
    ):
        raise HTTPException(status_code=409, detail="The Seller Agreement changed. Review the new version.")
    # Concurrent requests for the same text preserve the first acceptance time.
    db.execute(
        insert(SellerAgreementAcceptance)
        .values(
            seller_id=seller.id,
            version=form.version,
            content_sha256=form.content_sha256,
            accepted_at=utcnow(),
        )
        .on_conflict_do_nothing(index_elements=["seller_id", "version", "content_sha256"])
    )
    db.commit()
    return agreement_status(db, seller)


def seller_with_agreement(seller: CurrentSeller, db: DB) -> User:
    if acceptance(db, seller) is None:
        raise HTTPException(
            status_code=403,
            detail="Accept the current Seller Agreement in Sell data before uploading or publishing.",
        )
    return seller


AgreedSeller = Annotated[User, Depends(seller_with_agreement)]
