"""Sliver's platform fee (ADR 0005): recorded per sale, settled off-chain, never on the payment path.

The buyer still pays the full price to the seller with one standard x402 Payment; these tests
check the fee math, the snapshot on delivery, the seller's insights and the public views, and that
the 402 requirements do not depend on the fee.
"""

import pytest
import test_payments as harness
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sliver_api.config import Settings
from sliver_api.main import create_app
from sliver_api.models import Payment, Resource, User
from sliver_api.payments import fees
from sliver_api.payments.x402 import drops_for
from sliver_api.seed import seed
from sliver_api.seller.insights import insights

PRICE_MINOR = 450  # the seeded "October 2026" sliver
PRICE_DROPS = 1_800_000  # at the default 400,000 drops per USD

# --- the math ------------------------------------------------------------------------------


def test_fee_rounds_down_and_fee_plus_net_is_the_gross():
    assert fees.split(115, 1_000) == fees.Split(gross=115, fee=11, net=104)  # "you receive $1.04"
    assert fees.split(450, 1_000) == fees.Split(gross=450, fee=45, net=405)
    assert fees.split(1, 1_000) == fees.Split(gross=1, fee=0, net=1)  # a 1-cent sale owes nothing
    assert fees.split(9, 5_000) == fees.Split(gross=9, fee=4, net=5)
    assert fees.split(1_800_001, 1_000) == fees.Split(gross=1_800_001, fee=180_000, net=1_620_001)
    assert fees.split(123, 0) == fees.Split(gross=123, fee=0, net=123)
    for bps in (0, 1, 250, 999, 1_000, 3_333, 5_000):
        for gross in (0, 1, 7, 99, 100, 101, 12_345, 100_000_000, 400_000_000_000_000):
            result = fees.split(gross, bps)
            assert result.fee + result.net == gross
            # Exactly floor(gross * bps / 10,000): never more than the rate, short by under one unit.
            assert result.fee * 10_000 <= gross * bps < (result.fee + 1) * 10_000


@pytest.mark.parametrize("bps", [-1, 5_001])
def test_fee_math_refuses_rates_out_of_bounds(bps):
    with pytest.raises(ValueError):
        fees.split(100, bps)


def test_fee_math_refuses_negative_amounts():
    with pytest.raises(ValueError):
        fees.split(-1, 1_000)


# --- the setting ---------------------------------------------------------------------------

BASE = {
    "database_url": "postgresql+psycopg://u:p@db/sliver",
    "s3_endpoint_url": "http://127.0.0.1:9000",
    "s3_access_key_id": "key",
    "s3_secret_access_key": "secret",
}


def test_fee_rate_defaults_to_ten_percent(monkeypatch):
    monkeypatch.delenv("SLIVER_PLATFORM_FEE_BPS", raising=False)
    assert Settings(**BASE).sliver_platform_fee_bps == 1_000 == fees.DEFAULT_FEE_BPS


@pytest.mark.parametrize("value", ["0", "250", "5000"])
def test_fee_rate_is_read_from_the_environment(monkeypatch, value):
    monkeypatch.setenv("SLIVER_PLATFORM_FEE_BPS", value)
    assert Settings(**BASE).sliver_platform_fee_bps == int(value)


@pytest.mark.parametrize("value", ["-1", "5001", "10000", "ten", "10.5"])
def test_fee_rate_out_of_bounds_is_refused_at_startup(monkeypatch, value):
    monkeypatch.setenv("SLIVER_PLATFORM_FEE_BPS", value)
    with pytest.raises(ValidationError):
        Settings(**BASE)


# --- purchases -----------------------------------------------------------------------------


@pytest.fixture
def market(settings, engine, store, sessions):
    """Seeded catalog plus `buy_with(bps)`: a buyer client on an app running that fee rate."""
    seed(sessions, store, harness.FIXTURES)
    with sessions() as db:
        seller = db.scalar(select(User))
        seller.xrpl_address = harness.SELLER.address
        db.commit()
        resource_id = db.scalar(select(Resource).where(Resource.title.endswith("October 2026"))).id
        seller_id = seller.id
    ledger, clients = harness.StubLedger(), []

    def client_with(bps: int) -> TestClient:
        app = create_app(
            settings.model_copy(update={"sliver_platform_fee_bps": bps}),
            engine=engine,
            store=store,
            facilitator=harness.StubFacilitator(),
            ledger=ledger,
        )
        app.state.purchases.sleep = lambda _seconds: None
        app.state.purchases.ledger_attempts = 2
        client = TestClient(app).__enter__()
        clients.append(client)
        return client

    yield client_with, ledger, resource_id, seller_id
    for client in clients:
        client.__exit__(None, None, None)


def buy(client, resource_id, ledger):
    response, signed, header = harness.pay(client, resource_id, ledger)
    assert response.status_code == 200, response.text
    return response.headers["X-Sliver-Receipt"], signed, header


def test_a_delivered_sale_snapshots_the_fee_and_the_net(market, sessions):
    client_with, ledger, resource_id, _ = market
    payment_id, _, _ = buy(client_with(1_000), resource_id, ledger)
    with sessions() as db:
        payment = db.get(Payment, payment_id)
        assert payment.status == "delivered"
        assert payment.platform_fee_bps == 1_000
        assert (payment.platform_fee_minor, payment.seller_net_minor) == (45, 405)
        assert (payment.platform_fee_drops, payment.seller_net_drops) == (180_000, 1_620_000)
        assert payment.platform_fee_drops + payment.seller_net_drops == int(payment.amount) == PRICE_DROPS


def test_the_fee_never_changes_what_the_buyer_pays_or_to_whom(market, settings):
    client_with, _, resource_id, _ = market
    for bps in (0, 1_000, 5_000):
        (accepted,) = harness.challenge(client_with(bps), resource_id).json()["accepts"]
        assert accepted["payTo"] == harness.SELLER.address
        assert accepted["amount"] == drops_for(PRICE_MINOR, settings.drops_per_usd) == str(PRICE_DROPS)


def test_a_later_rate_change_never_rewrites_an_earlier_sale(market, sessions):
    client_with, ledger, resource_id, _ = market
    first_client = client_with(1_000)
    first, _, first_header = buy(first_client, resource_id, ledger)
    later = client_with(2_500)
    second, _, _ = buy(later, resource_id, ledger)
    # Replaying the first payment on the app with the new rate re-delivers without re-pricing it.
    replay = later.get(f"/api/resources/{resource_id}/data", headers={"PAYMENT-SIGNATURE": first_header})
    assert replay.status_code == 200
    with sessions() as db:
        old, new = db.get(Payment, first), db.get(Payment, second)
        assert (old.platform_fee_bps, old.platform_fee_minor, old.platform_fee_drops) == (1_000, 45, 180_000)
        assert (new.platform_fee_bps, new.platform_fee_minor, new.platform_fee_drops) == (2_500, 112, 450_000)
        assert (new.seller_net_minor, new.seller_net_drops) == (338, 1_350_000)


def test_recording_the_fee_never_blocks_delivery(market, sessions, monkeypatch):
    client_with, ledger, resource_id, _ = market

    def broken(*_args):
        raise RuntimeError("bookkeeping bug")

    monkeypatch.setattr("sliver_api.payments.service.record_fee", broken)
    payment_id, _, _ = buy(client_with(1_000), resource_id, ledger)
    with sessions() as db:
        payment = db.get(Payment, payment_id)
        assert payment.status == "delivered" and payment.platform_fee_bps is None


def test_record_fee_never_replaces_a_recorded_fee():
    payment = Payment(amount="1000", asset="XRP", price_minor=100, platform_fee_bps=None)
    fees.record_fee(payment, 1_000)
    fees.record_fee(payment, 5_000)
    assert payment.platform_fee_bps == 1_000
    assert (payment.platform_fee_minor, payment.platform_fee_drops) == (10, 100)


def test_record_fee_keeps_only_usd_figures_for_non_drop_amounts():
    payment = Payment(amount="1.5", asset="RLUSD", price_minor=150, platform_fee_bps=None)
    fees.record_fee(payment, 1_000)
    assert (payment.platform_fee_minor, payment.seller_net_minor) == (15, 135)
    assert payment.platform_fee_drops is None and payment.seller_net_drops is None


def test_the_database_refuses_an_inconsistent_fee(market, sessions):
    client_with, ledger, resource_id, _ = market
    payment_id, _, _ = buy(client_with(1_000), resource_id, ledger)
    with sessions() as db:
        db.get(Payment, payment_id).seller_net_minor = 999
        with pytest.raises(IntegrityError):
            db.commit()


# --- seller insights -----------------------------------------------------------------------


def test_insights_show_gross_fee_net_and_fee_owed(market, sessions):
    client_with, ledger, resource_id, seller_id = market
    pre_fee, _, _ = buy(client_with(1_000), resource_id, ledger)
    with sessions() as db:  # a sale delivered before 0008_platform_fee: no fee recorded
        payment = db.get(Payment, pre_fee)
        payment.platform_fee_bps = payment.platform_fee_minor = payment.seller_net_minor = None
        payment.platform_fee_drops = payment.seller_net_drops = None
        db.commit()
    at_ten, _, _ = buy(client_with(1_000), resource_id, ledger)
    at_quarter, _, _ = buy(client_with(2_500), resource_id, ledger)

    with sessions() as db:
        body = insights(db, db.get(User, seller_id), 2_500)
    assert body["platform_fee"] == {"bps": 2_500, "settlement": "off_chain"}
    earnings = body["earnings"]
    assert earnings["purchases"] == 3 and earnings["purchases_without_fee"] == 1
    assert (earnings["usd_minor"], earnings["xrp_drops"]) == (3 * PRICE_MINOR, str(3 * PRICE_DROPS))
    assert earnings["platform_fee"] == {"usd_minor": 45 + 112, "xrp_drops": str(180_000 + 450_000)}
    assert earnings["fee_owed"] == earnings["platform_fee"]
    assert earnings["net"] == {
        "usd_minor": PRICE_MINOR + 405 + 338,
        "xrp_drops": str(PRICE_DROPS + 1_620_000 + 1_350_000),
    }
    assert earnings["net"]["usd_minor"] + earnings["platform_fee"]["usd_minor"] == earnings["usd_minor"]

    items = {item["payment_id"]: item for item in earnings["items"]}
    assert items[pre_fee]["platform_fee"] is None
    assert items[pre_fee]["net"] == {"usd_minor": PRICE_MINOR, "xrp_drops": str(PRICE_DROPS)}
    assert items[at_ten]["platform_fee"] == {"bps": 1_000, "usd_minor": 45, "xrp_drops": "180000"}
    assert items[at_ten]["net"] == {"usd_minor": 405, "xrp_drops": "1620000"}
    assert items[at_quarter]["platform_fee"] == {"bps": 2_500, "usd_minor": 112, "xrp_drops": "450000"}


def test_insights_without_sales_owe_nothing(market, sessions):
    _, _, _, seller_id = market
    with sessions() as db:
        earnings = insights(db, db.get(User, seller_id), 1_000)["earnings"]
    zero = {"usd_minor": 0, "xrp_drops": "0"}
    assert earnings["platform_fee"] == earnings["net"] == earnings["fee_owed"] == zero
    assert earnings["purchases"] == earnings["purchases_without_fee"] == 0


# --- public views --------------------------------------------------------------------------

PUBLIC_FEE = {
    "bps": 1_000,
    "settlement": "off_chain",
    "fee": {"usd_minor": 45, "xrp_drops": "180000"},
    "seller_net": {"usd_minor": 405, "xrp_drops": "1620000"},
}


def test_receipt_and_timeline_state_the_split_and_nothing_else(market):
    client_with, ledger, resource_id, _ = market
    client = client_with(1_000)
    payment_id, _, _ = buy(client, resource_id, ledger)
    receipt = client.get(f"/api/receipts/{payment_id}").json()
    timeline = client.get(f"/api/purchases/{payment_id}").json()
    assert receipt["platform_fee"] == timeline["platform_fee"] == PUBLIC_FEE
    # The buyer still paid the full price to the seller.
    assert receipt["pay_to"] == harness.SELLER.address and receipt["amount"]["value"] == str(PRICE_DROPS)
    # Events are unchanged: the fee lives on the purchase, not in the public event allow-list.
    assert all("platform_fee" not in event for event in timeline["events"])


def test_unpaid_and_pre_fee_purchases_show_no_fee(market, sessions):
    client_with, ledger, resource_id, _ = market
    client = client_with(1_000)
    harness.challenge(client, resource_id)
    with sessions() as db:
        unpaid = db.scalar(select(Payment).where(Payment.status == "required")).id
    assert client.get(f"/api/purchases/{unpaid}").json()["platform_fee"] is None

    payment_id, _, _ = buy(client, resource_id, ledger)
    with sessions() as db:
        payment = db.get(Payment, payment_id)
        payment.platform_fee_bps = payment.platform_fee_minor = payment.seller_net_minor = None
        payment.platform_fee_drops = payment.seller_net_drops = None
        db.commit()
    assert client.get(f"/api/receipts/{payment_id}").json()["platform_fee"] is None
    assert client.get(f"/api/purchases/{payment_id}").json()["platform_fee"] is None
