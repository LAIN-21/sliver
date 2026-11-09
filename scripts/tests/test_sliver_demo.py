"""Pure parts of `make demo`: the README block, the Testnet guards, the ledger facts, the demo
dataset and the two buyer questions. Run with the buyer packages: `cd packages && uv run pytest`."""

import csv
import io
import sys
from datetime import date
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


def run_record(title: str = "Singapore anchorage waiting times: October 2026") -> dict:
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
        "dataset_title": "Singapore anchorage waiting times, daily (demo run 20261109T120000Z)",
        "dataset_rows": 184,
        "acceptance": "accepted automatically (quality 88)",
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


@pytest.mark.parametrize(
    ("status", "decision", "expected"),
    [
        ("review", {"decision": "review", "quality_score": 68, "threshold": 70, "blocking": []}, True),
        ("accepted", {"decision": "accepted", "quality_score": 88, "threshold": 70, "blocking": []}, False),
        ("rejected", {"decision": "review", "quality_score": 68, "threshold": 70, "blocking": []}, False),
        (
            "review",
            {"decision": "review", "quality_score": 90, "threshold": 70, "blocking": [{"code": "pii_email"}]},
            False,
        ),
        (
            "review",
            {
                "decision": "review",
                "quality_score": 60,
                "threshold": 70,
                "blocking": [{"code": "near_duplicate"}],
            },
            False,
        ),
        ("review", {"decision": "review", "threshold": 70, "blocking": []}, False),
        ("review", {}, False),
    ],
)
def test_demo_reviewer_approves_only_a_quality_score_miss(status, decision, expected):
    assert demo.reviewable(status, decision) is expected


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
    days = [date.fromisoformat(row[0]) for row in rows]
    assert days == sorted(days) and len(set(days)) == len(days)
    assert days[0] == date(2026, 5, 1) and days[-1] == date(2026, 10, 31)  # six whole months
    assert all((later - earlier).days == 1 for earlier, later in zip(days, days[1:], strict=False))
    assert {row[1] for row in rows} == {"Singapore"}
    assert all(float(value) > 0 for row in rows for value in row[2:])
    assert all("." in value for row in rows for value in row[2:])  # decimals, never category values


def test_dataset_can_only_be_sliced_by_month(generator):
    """No column but `date` has between 2 and 50 distinct short values, so neither Claude nor
    the offline rule can slice the demo table by anything other than calendar month."""
    _, *rows = table(generator.generate("run-1", TODAY))
    for index, name in enumerate(generator.HEADER[1:], start=1):
        distinct = {row[index] for row in rows}
        assert len(distinct) == 1 or len(distinct) * 2 > len(rows), name
    assert len({row[0][:7] for row in rows}) >= 2


def month_listing(generator, run: str, month: str | None, *, price_minor: int) -> dict:
    """A published sliver of the demo table as the catalog describes it: the full table, or the
    slice for one calendar month."""
    days = [row[0] for row in generator.rows(run, TODAY) if month is None or row[0].startswith(month)]
    label = None if month is None else date.fromisoformat(f"{month}-01").strftime("%B %Y")
    return {
        "id": f"{run}-{month or 'full'}",
        "title": "Singapore anchorage waiting times, daily" + (f": {label}" if label else ""),
        "description": f"{len(days)} rows with 5 columns.",
        "category": "port-operations",
        "tags": ["port", "container", "ship", "wait", "tanker", "bulk", "carrier", "vessels", "anchorage"],
        "columns": [{"name": name} for name in generator.HEADER],
        "coverage": {
            "time": {"start": days[0], "end": days[-1]},
            **({"slice": {"column": "date", "value": label}} if label else {}),
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


SEEDED = {
    "id": "berth",
    "title": "Singapore berth waiting times",
    "columns": [{"name": "date"}, {"name": "terminal"}],
    "coverage": {"time": {"start": "2026-08-01", "end": "2026-10-31"}},
    "price": {"amount_minor": 450, "currency": "USD"},
}


def demo_listings(generator, run: str = "run-1") -> list[dict]:
    months = sorted({row[0][:7] for row in generator.rows(run, TODAY)})
    return [
        month_listing(generator, run, None, price_minor=283),
        *(month_listing(generator, run, month, price_minor=165) for month in months),
    ]


def test_last_month():
    assert demo.last_month(date(2026, 11, 9)) == date(2026, 10, 1)
    assert demo.last_month(date(2026, 1, 1)) == date(2025, 12, 1)
    assert demo.last_month(date(2026, 3, 31)) == date(2026, 2, 1)


def test_questions_get_the_expected_answers(generator):
    miss, hit = demo.questions(TODAY)
    assert "October 2026" in hit.ask and hit.time_start == hit.time_end == "2026-10"
    listings = [SEEDED, *demo_listings(generator)]
    assert ask(miss, listings)["recommendation"] == miss.expect == "look_elsewhere"
    report = ask(hit, listings)
    assert report["recommendation"] == hit.expect == "buy"
    assert report["best"] == "run-1-2026-10"  # last month's sliver, not the dearer full table
    verdicts = {c["resource_id"]: c["verdict"] for c in report["candidates"]}
    assert verdicts["run-1-full"] == "buy" and verdicts["run-1-2026-09"] == "look_elsewhere"
    assert verdicts["berth"] == "look_elsewhere"


def test_buy_question_holds_without_claude_metadata(generator):
    """Claude's listing may not say "Singapore" (it never sees the seller's title): the column
    names alone still cover enough of the need."""
    _, hit = demo.questions(TODAY)
    bare = [{**item, "title": "Uploaded table", "tags": []} for item in demo_listings(generator)]
    assert ask(hit, bare)["best"] == "run-1-2026-10"


def test_buy_question_skips_what_the_budget_does_not_cover(generator):
    _, hit = demo.questions(TODAY)
    report = ask(hit, [month_listing(generator, "run-1", "2026-10", price_minor=650)])
    assert report["recommendation"] == "skip"
