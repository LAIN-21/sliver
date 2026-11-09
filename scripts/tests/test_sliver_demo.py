"""Pure parts of `make demo`: the README block, the Testnet guards, the ledger facts, the demo
dataset and the two buyer questions. Run with the buyer packages: `cd packages && uv run pytest`."""

import csv
import io
import sys
from datetime import date, timedelta
from pathlib import Path

import httpx
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

import sliver_demo as demo  # noqa: E402

from sliver_mcp.evaluate import evaluate  # noqa: E402

HASH = "A" * 64
BUYER = "rBuyerAddressxxxxxxxxxxxxxxxxxxxx"
SELLER = "rSellerAddressxxxxxxxxxxxxxxxxxxx"
README = f"""# Sliver

Intro.

### Testnet transactions from `make demo`

{demo.START}
_Placeholder._
{demo.END}

## Next section

Text after.
"""


def validated_tx(**overrides) -> dict:
    result = {
        "hash": HASH,
        "validated": True,
        "ledger_index": 12_345_678,
        "TransactionType": "Payment",
        "Account": BUYER,
        "Destination": SELLER,
        "InvoiceID": "B" * 64,
        "SourceTag": 804681468,
        "meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": "700000"},
    }
    result.update(overrides)
    return result


def run_record(title: str = "Bunker fuel prices: Singapore") -> dict:
    return {
        "run_id": "20261109T120000Z",
        "finished_at": "2026-11-09 12:05 UTC",
        "rpc_host": "s.altnet.rippletest.net",
        "transactions": [
            {
                **demo.ledger_facts(validated_tx(), HASH),
                "price_minor": 175,
                "title": title,
            }
        ],
        "dataset_title": "Bunker fuel prices at five ports (demo run 20261109T120000Z)",
        "dataset_rows": 390,
        "quality_score": 100,
        "review_engine": "offline fallback",
        "published": 6,
        "answers": [
            {"ask": "Air cargo? Budget $5.", "recommendation": "look_elsewhere", "tx_hash": None},
            {
                "ask": "Bunker prices? Budget $5.",
                "recommendation": "buy",
                "tx_hash": HASH,
                "title": title,
                "price_minor": 175,
            },
        ],
    }


# --- README block ---------------------------------------------------------------------------


def test_replace_block_changes_only_the_block():
    updated = demo.replace_block(README, "new content")
    before, after = README.split(demo.START)[0], README.split(demo.END)[1]
    assert updated.startswith(before + demo.START + "\nnew content\n" + demo.END)
    assert updated.endswith(demo.END + after)
    assert "_Placeholder._" not in updated


def test_replace_block_is_repeatable():
    once = demo.replace_block(README, "first run")
    twice = demo.replace_block(once, "second run")
    assert twice == demo.replace_block(README, "second run")
    assert "first run" not in twice


@pytest.mark.parametrize(
    "text",
    [
        "# README without markers\n",
        f"only the start {demo.START}\n",
        f"only the end {demo.END}\n",
        f"{demo.END}\nreversed\n{demo.START}\n",
        f"{demo.START}\n{demo.END}\n{demo.START}\n{demo.END}\n",
    ],
)
def test_missing_or_broken_markers_fail_loudly(text):
    with pytest.raises(demo.DemoError):
        demo.replace_block(text, "hashes")
    with pytest.raises(demo.DemoError):
        demo.find_block(text)


def test_render_block_records_ledger_facts_and_links():
    block = demo.render_block(run_record())
    assert f"[`{HASH}`](https://testnet.xrpl.org/transactions/{HASH})" in block
    assert "| 12345678 |" in block
    assert "0.7 XRP ($1.75)" in block
    assert f"[`{BUYER}`](https://testnet.xrpl.org/accounts/{BUYER})" in block
    assert f"[`{SELLER}`](https://testnet.xrpl.org/accounts/{SELLER})" in block
    assert "`look_elsewhere`: nothing was signed or spent." in block
    assert "run `20261109T120000Z`" in block
    assert demo.START not in block and demo.END not in block


def test_render_block_escapes_listing_text():
    block = demo.render_block(run_record(title="Prices | <script>x</script> [link](http://evil)"))
    row = next(line for line in block.splitlines() if line.startswith("| [`"))
    assert row.count(" | ") == 4  # the title's pipe cannot add a column
    assert "<script>" not in block and "[link](" not in block
    assert r"\<script\>" in block and r"\[link\](http://evil)" in block


def test_xrp_formatting():
    assert demo.xrp(700_000) == "0.7"
    assert demo.xrp(1_000_000) == "1"
    assert demo.xrp(1) == "0.000001"


# --- Testnet guards and ledger facts --------------------------------------------------------


@pytest.mark.parametrize(
    "url", ["https://s.altnet.rippletest.net:51234/", "https://s.altnet.rippletest.net:51234"]
)
def test_testnet_rpc_accepted(url):
    assert demo.testnet_rpc(url) == "https://s.altnet.rippletest.net:51234/"


@pytest.mark.parametrize("url", ["https://s1.ripple.com:51234/", "https://xrplcluster.com/", ""])
def test_anything_but_testnet_is_refused(url):
    with pytest.raises(demo.DemoError, match="Testnet"):
        demo.testnet_rpc(url)


def test_directory_must_be_testnet_only():
    demo.check_directory({"items": [{"price": {"network": "xrpl:1"}}]})
    demo.check_directory({"items": []})
    with pytest.raises(demo.DemoError):
        demo.check_directory({"items": [{"price": {"network": "xrpl:1"}}, {"price": {"network": "xrpl:0"}}]})


def test_ledger_facts_from_api_v1_and_v2_shapes():
    facts = demo.ledger_facts(validated_tx(), HASH.lower())
    assert facts == {
        "hash": HASH,
        "ledger_index": 12_345_678,
        "account": BUYER,
        "destination": SELLER,
        "delivered_drops": 700_000,
        "invoice_id": "B" * 64,
        "source_tag": 804681468,
    }
    v1 = validated_tx()
    v2 = {
        "hash": HASH,
        "validated": True,
        "ledger_index": 12_345_678,
        "meta": v1.pop("meta"),
        "tx_json": {k: v for k, v in v1.items() if k not in ("hash", "validated", "ledger_index")},
    }
    assert demo.ledger_facts(v2, HASH) == facts


@pytest.mark.parametrize(
    "overrides",
    [
        {"validated": False},
        {"hash": "C" * 64},
        {"TransactionType": "OfferCreate"},
        {"meta": {"TransactionResult": "tecUNFUNDED_PAYMENT", "delivered_amount": "0"}},
        {"meta": {"TransactionResult": "tesSUCCESS", "delivered_amount": {"currency": "USD", "value": "1"}}},
        {"ledger_index": None},
    ],
)
def test_ledger_facts_refuse_anything_but_a_validated_xrp_payment(overrides):
    with pytest.raises(demo.DemoError):
        demo.ledger_facts(validated_tx(**overrides), HASH)


def test_read_ledger_tx_waits_for_validation():
    answers = iter([{"validated": False}, {"error": "txnNotFound"}, validated_tx()])
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={"result": next(answers)})

    client = httpx.Client(transport=httpx.MockTransport(handler))
    result = demo.read_ledger_tx(client, "https://s.altnet.rippletest.net:51234/", HASH, sleep=lambda _: None)
    assert result["validated"] is True
    assert len(requests) == 3
    assert b'"method":"tx"' in requests[0].content.replace(b" ", b"")


def test_read_ledger_tx_gives_up():
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={"result": {}})))
    with pytest.raises(demo.DemoError, match="not validated"):
        demo.read_ledger_tx(client, "https://x/", HASH, attempts=2, sleep=lambda _: None)


def test_read_env_never_needs_quotes_and_skips_comments(tmp_path):
    path = tmp_path / ".env"
    path.write_text("# comment\nA=1\nB = two words \n\nC=\n")
    assert demo.read_env(path) == {"A": "1", "B": "two words", "C": ""}
    assert demo.read_env(tmp_path / "missing") == {}


# --- the demo dataset and the two questions -------------------------------------------------

TODAY = date(2026, 11, 11)  # a Wednesday


@pytest.fixture(scope="module")
def generator():
    return demo.load_generator(ROOT / "examples" / "demo" / "generate.py")


def table(data: bytes) -> list[list[str]]:
    return list(csv.reader(io.StringIO(data.decode("utf-8"))))


def test_dataset_is_deterministic_per_run_and_new_each_run(generator):
    first = generator.generate("run-1", TODAY)
    assert first == generator.generate("run-1", TODAY)
    rows_1, rows_2 = table(first)[1:], table(generator.generate("run-2", TODAY))[1:]
    assert not {tuple(row) for row in rows_1} & {tuple(row) for row in rows_2}


def test_dataset_shape(generator):
    header, *rows = table(generator.generate("run-1", TODAY))
    assert header == generator.HEADER
    assert len(rows) == generator.WEEKS * len(generator.PORTS) * len(generator.GRADES)
    weeks = sorted({row[0] for row in rows})
    assert weeks[-1] == "2026-11-09"  # the Monday of the run's week
    assert len(weeks) == generator.WEEKS
    assert all(float(row[3]) > 0 and int(row[4]) >= 2 for row in rows)


def listing(generator, *, label: str | None, end: date, price_minor: int = 175) -> dict:
    """A published sliver of the demo dataset as the catalog describes it (offline fallback)."""
    weeks = generator.week_starts(end)
    return {
        "id": f"res-{label or 'full'}-{end}",
        "title": "Bunker fuel prices at five ports" + (f": {label}" if label else ""),
        "description": "390 rows with 5 columns.",
        "category": "port-operations",
        "tags": ["port", "fuel", "grade", "bunker", "price", "tonne"],
        "columns": [{"name": name} for name in generator.HEADER],
        "coverage": {
            "time": {"start": weeks[0].isoformat(), "end": weeks[-1].isoformat()},
            **({"slice": {"column": "port", "value": label}} if label else {}),
        },
        "price": {"amount_minor": price_minor, "currency": "USD"},
    }


def ask(question: demo.Question, listings: list[dict]) -> dict:
    return evaluate(
        listings,
        need=question.need,
        today=TODAY,
        required_columns=list(question.required_columns),
        required_terms=[],
        time_start=question.time_start,
        time_end=question.time_end,
        max_age_days=question.max_age_days,
        budget_minor=demo.BUDGET_USD * 100,
    )


def test_questions_get_the_expected_answers(generator):
    miss, hit = demo.questions(TODAY)
    fresh = [listing(generator, label=port, end=TODAY) for port in ("Busan", "Singapore")]
    fresh.append(listing(generator, label=None, end=TODAY, price_minor=320))
    seeded = {
        "id": "berth",
        "title": "Singapore berth waiting times",
        "columns": [{"name": "date"}, {"name": "terminal"}],
        "coverage": {"time": {"start": "2026-08-01", "end": "2026-10-31"}},
        "price": {"amount_minor": 450, "currency": "USD"},
    }
    assert ask(miss, [*fresh, seeded])["recommendation"] == miss.expect == "look_elsewhere"
    report = ask(hit, [seeded, *fresh])
    assert report["recommendation"] == hit.expect == "buy"
    assert report["best"] == "res-Singapore-2026-11-11"


def test_buy_question_prefers_this_run_over_an_older_run(generator):
    _, hit = demo.questions(TODAY)
    older = listing(generator, label="Singapore", end=TODAY - timedelta(weeks=1), price_minor=100)
    fresh = listing(generator, label="Singapore", end=TODAY, price_minor=175)
    assert ask(hit, [older, fresh])["best"] == fresh["id"]
    stale = listing(generator, label="Singapore", end=TODAY - timedelta(weeks=4), price_minor=100)
    assert ask(hit, [stale])["recommendation"] == "skip"


def test_buy_question_skips_what_the_budget_does_not_cover(generator):
    _, hit = demo.questions(TODAY)
    report = ask(hit, [listing(generator, label="Singapore", end=TODAY, price_minor=650)])
    assert report["recommendation"] == "skip"
