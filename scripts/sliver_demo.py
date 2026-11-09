"""`make demo`: the whole Sliver story on XRPL Testnet with one command.

1. Preflight: Testnet only, the API is healthy, README.md has its transaction block.
2. A demo seller signs in and uploads a fresh synthetic table (examples/demo/generate.py).
3. The acceptance pipeline runs; the demo waits for its decision.
4. The seller takes the suggested prices, picks a few public sample rows and publishes.
5. A scripted buyer uses the Sliver MCP's own code (catalog search, the deterministic evaluator,
   the custom-slice quote and the budget-capped Buyer that signs locally) for three questions,
   each with a $5 budget: one Sliver cannot answer (look_elsewhere: nothing is signed), one a
   sliver of the fresh upload answers, and one about running a port business in Singapore, for
   which it quotes a custom slice of the seeded operating-cost table, shows the quote, and buys
   it only after a scripted "yes" within the budget.
6. Every purchase pays Sliver's platform wallet (ADR 0005). The seller's insights must show each
   sale credited to the seller: the gross, Sliver's fee and the net owed at the next payout.
7. Every transaction is read back from XRPL Testnet. Only validated, successful Payments from
   the buyer to Sliver's platform wallet are written into README.md, between the demo-tx markers.

It runs in the API container (see the Makefile) against the running stack. Nothing is reset or
deleted: each run uploads a new, uniquely seeded table, so the demo can be re-run. Passwords
and wallet seeds come from the environment and `.env` and are never printed.
"""

import argparse
import importlib.util
import os
import re
import sys
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
from xrpl.wallet import Wallet

from sliver_mcp.api import ApiError, SliverApi
from sliver_mcp.buyer import Buyer, Refused, XrplSigner
from sliver_mcp.config import Config, usd_to_minor
from sliver_mcp.evaluate import evaluate
from sliver_mcp.quote import quote_summary
from sliver_mcp.store import Store
from sliver_x402 import TESTNET, TESTNET_RPC_URLS, PaymentRejected, check_rpc_url, explorer_url

ROOT = Path(__file__).resolve().parents[1]
START = "<!-- demo-tx:start -->"
END = "<!-- demo-tx:end -->"
DEMO_SELLER = "strait-line-data@sliver.local"
DEMO_REVIEWER = "reviewer@sliver.local"
BUYER_SEED_VAR = "SLIVER_DEMO_BUYER_SEED"
PLATFORM_ADDRESS_VAR = "SLIVER_PLATFORM_ADDRESS"  # an address, not a secret; never the seed
BUDGET_USD = 5
STEPS = 9
PUBLIC_SAMPLE_ROWS = 3
DECIDED = frozenset({"accepted", "review", "rejected", "published"})
STEP_DONE = frozenset({"passed", "warning", "failed", "skipped"})
PIPELINE_TIMEOUT_SECONDS = 900
ACCOUNT_URL = "https://testnet.xrpl.org/accounts/{}"


class DemoError(RuntimeError):
    """The demo cannot continue. The message says why and what to do; it never holds a secret."""


# --- README transaction block ---------------------------------------------------------------


def find_block(text: str) -> tuple[int, int]:
    """Start and end offsets of the block's content. Exactly one pair of markers, in order."""
    if text.count(START) != 1 or text.count(END) != 1:
        raise DemoError(
            f"README.md must contain exactly one {START} and one {END} marker; found "
            f"{text.count(START)} and {text.count(END)}. Refusing to write transaction hashes anywhere else."
        )
    start, end = text.index(START) + len(START), text.index(END)
    if end < start:
        raise DemoError(f"In README.md, {END} comes before {START}.")
    return start, end


def replace_block(text: str, block: str) -> str:
    """`text` with only the content between the markers replaced by `block`."""
    start, end = find_block(text)
    return f"{text[:start]}\n{block.strip()}\n{text[end:]}"


def md(value: object) -> str:
    """Untrusted listing text for one Markdown table cell or list item."""
    text = re.sub(r"\s+", " ", str(value)).strip()
    return re.sub(r"([\\|`*_\[\]<>])", r"\\\1", text)


def xrp(drops: int) -> str:
    return f"{drops / 1_000_000:,.6f}".rstrip("0").rstrip(".")


def usd(minor: int) -> str:
    return f"${minor / 100:.2f}"


def credit_text(credit: dict) -> str:
    """How one sale is credited to the seller: gross, Sliver's fee and the net owed."""
    return (
        f"{usd(credit['gross_minor'])} − {usd(credit['fee_minor'])} Sliver fee "
        f"({credit['fee_bps'] / 100:g}%) = {usd(credit['net_minor'])} net, "
        f"owed at the {credit['next_payout_date']} payout"
    )


def answer_text(answer: dict) -> str:
    if answer["tx_hash"] is None:
        return f"`{answer['recommendation']}`: nothing was signed or spent."
    paid = (
        f"for {usd(answer['price_minor'])}: paid to Sliver's platform wallet, delivered and SHA-256-verified."
    )
    quote = answer.get("quote")
    if quote is None:
        return f"`{answer['recommendation']}` “{md(answer['title'])}” {paid}"
    return (
        f"`sliver_evaluate` suggested a custom slice; `sliver_quote_slice` quoted "
        f"{quote['rows']:,} rows × {quote['column_count']} columns of “{md(quote['parent_title'])}” "
        f"({md(quote['covers'])}) for {usd(quote['price_minor'])} ({xrp(quote['amount_drops'])} XRP). "
        f"The scripted human said yes, and the buyer bought it {paid}"
    )


def render_block(run: dict[str, Any]) -> str:
    """The README block for one demo run. Every number comes from the run and the ledger."""
    platform = run["platform_address"]
    lines = [
        f"_Written by `make demo` on {run['finished_at']} (run `{run['run_id']}`). "
        f"Each transaction was read back from XRPL Testnet (`{run['rpc_host']}`): a validated "
        "`tesSUCCESS` Payment from the buyer's wallet to Sliver's platform wallet "
        f"[`{platform}`]({ACCOUNT_URL.format(platform)}). Sliver recorded its fee and the seller's "
        "net on each sale; the net is owed to the seller and paid out on the 1st and 16th of each "
        "month (UTC; payouts are not automated yet, see ADR 0005). "
        "Re-run `make demo` to replace this block; do not edit it by hand._",
        "",
        "| Transaction | Ledger | Paid by the buyer | Buyer → Sliver's platform wallet | Sliver "
        "| Credited to the seller |",
        "|---|---|---|---|---|---|",
    ]
    for tx in run["transactions"]:
        lines.append(
            f"| [`{tx['hash']}`]({explorer_url(tx['hash'])}) | {tx['ledger_index']} "
            f"| {xrp(tx['delivered_drops'])} XRP ({usd(tx['price_minor'])}) "
            f"| [`{tx['account']}`]({ACCOUNT_URL.format(tx['account'])}) → "
            f"[`{tx['destination']}`]({ACCOUNT_URL.format(tx['destination'])}) "
            f"| {md(tx['title'])} | {md(tx['seller'])}: {credit_text(tx['credit'])} |"
        )
    lines += [
        "",
        f"In this run the demo seller uploaded “{md(run['dataset_title'])}” ({run['dataset_rows']} rows). "
        f"It was {run['acceptance']} after the pipeline's checks (AI review: {md(run['review_engine'])}), "
        f"and the seller published {run['published']} slivers at their suggested prices. "
        f"The buyer then asked {len(run['answers'])} questions with a ${BUDGET_USD} budget each, using "
        "the Sliver MCP's own search, evaluator, custom-slice quote and budget-capped buyer:",
        "",
    ]
    for number, answer in enumerate(run["answers"], start=1):
        lines.append(f"{number}. “{md(answer['ask'])}” → {answer_text(answer)}")
    balance = run["balance"]
    lines += [
        "",
        f"Afterwards the seller's balance on `/sell/insights` showed {usd(balance['owed_minor'])} owed "
        f"by Sliver across {balance['sales_owed']} sales, with the next payout on "
        f"{balance['next_payout_date']}.",
    ]
    return "\n".join(lines)


# --- XRPL Testnet -------------------------------------------------------------------------


def testnet_rpc(url: str) -> str:
    """The configured XRPL RPC URL if it is a Testnet endpoint; anything else stops the demo."""
    normalized = url.strip()
    if normalized and not normalized.endswith("/"):
        normalized += "/"
    try:
        return check_rpc_url(normalized)
    except PaymentRejected:
        raise DemoError(
            f"XRPL_RPC_URL must be an XRPL Testnet endpoint ({', '.join(TESTNET_RPC_URLS)}). "
            "The demo never runs anywhere else."
        ) from None


def check_directory(directory: dict) -> None:
    """Every paid endpoint the API advertises must be on XRPL Testnet."""
    networks = {(item.get("price") or {}).get("network") for item in directory.get("items") or []}
    if networks - {TESTNET}:
        raise DemoError(
            f"The API advertises networks {sorted(map(str, networks))}; only {TESTNET} is allowed."
        )


def ledger_facts(result: dict, tx_hash: str) -> dict:
    """The facts the README records, from a validated `tx` result. Anything else is refused."""
    tx = result.get("tx_json") or result
    meta = result.get("meta") or {}
    if str(result.get("hash", tx.get("hash", ""))).upper() != tx_hash.upper():
        raise DemoError(f"The ledger returned a different transaction for {tx_hash}.")
    if result.get("validated") is not True:
        raise DemoError(f"{tx_hash} is not validated on XRPL Testnet.")
    if tx.get("TransactionType") != "Payment" or meta.get("TransactionResult") != "tesSUCCESS":
        raise DemoError(f"{tx_hash} is not a successful Payment ({meta.get('TransactionResult')}).")
    delivered = meta.get("delivered_amount", meta.get("DeliveredAmount"))
    if not isinstance(delivered, str) or not delivered.isdigit():
        raise DemoError(f"{tx_hash} did not deliver XRP.")
    ledger_index = result.get("ledger_index", tx.get("ledger_index"))
    if not isinstance(ledger_index, int):
        raise DemoError(f"{tx_hash} has no ledger index.")
    return {
        "hash": tx_hash.upper(),
        "ledger_index": ledger_index,
        "account": tx["Account"],
        "destination": tx["Destination"],
        "delivered_drops": int(delivered),
        "invoice_id": tx.get("InvoiceID"),
        "source_tag": tx.get("SourceTag"),
    }


def read_ledger_tx(
    http: httpx.Client, rpc_url: str, tx_hash: str, *, attempts: int = 20, sleep: Callable = time.sleep
) -> dict:
    """`tx` from XRPL Testnet, waiting until the ledger holding it is validated."""
    result: dict = {}
    for _ in range(attempts):
        try:
            response = http.post(
                rpc_url,
                json={
                    "method": "tx",
                    "params": [{"transaction": tx_hash, "binary": False, "api_version": 1}],
                },
            )
            result = response.json().get("result") or {}
        except (httpx.HTTPError, ValueError):
            result = {}
        if result.get("validated") is True:
            return result
        sleep(3)
    raise DemoError(
        f"{tx_hash} was not validated on XRPL Testnet in time ({result.get('error', 'pending')})."
    )


# --- helpers ------------------------------------------------------------------------------


def reviewable(status: str, decision: dict) -> bool:
    """A dataset the demo reviewer may approve: waiting for review only because its quality score
    is below the threshold, with no blocking finding (privacy, duplicates, sensitivity, errors)."""
    score, threshold = decision.get("quality_score"), decision.get("threshold")
    return (
        status == "review"
        and decision.get("decision") == "review"
        and not decision.get("blocking")
        and isinstance(score, int)
        and isinstance(threshold, int)
        and score < threshold
    )


def read_env(path: Path) -> dict[str, str]:
    values = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                name, value = line.split("=", 1)
                values[name.strip()] = value.strip()
    return values


def load_generator(path: Path):
    spec = importlib.util.spec_from_file_location("sliver_demo_dataset", path)
    if spec is None or spec.loader is None:
        raise DemoError(f"Cannot load the demo dataset generator {path}.")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def checked(response: httpx.Response, what: str) -> Any:
    if response.status_code >= 400:
        try:
            detail = response.json().get("detail") or response.json().get("error")
        except ValueError:
            detail = response.text[:200]
        raise DemoError(f"{what} failed: HTTP {response.status_code} {detail}")
    return response.json()


def say(text: str = "") -> None:
    print(text, flush=True)


def step(number: int, title: str) -> None:
    say()
    say(f"[{number}/{STEPS}] {title}")


@dataclass(frozen=True)
class Question:
    ask: str  # what the human asks the agent
    need: str  # what the agent passes to sliver_evaluate
    required_columns: tuple[str, ...]
    expect: str
    time_start: str | None = None
    time_end: str | None = None
    max_age_days: int | None = None
    reason: str | None = None  # what the agent tells Sliver (X-Sliver-Agent-Note), when it buys


def last_month(today: date) -> date:
    """The first day of the calendar month before `today`."""
    return (today.replace(day=1) - timedelta(days=1)).replace(day=1)


def questions(today: date) -> tuple[Question, Question]:
    """One need Sliver cannot meet, and one that exactly one sliver of the fresh upload meets:
    the demo table is sliced by calendar month (see examples/demo/generate.py)."""
    miss = Question(
        ask=f"Air-cargo rates from Singapore Changi (SIN) to Frankfurt (FRA), per kg. Budget ${BUDGET_USD}.",
        need="air cargo rates Singapore Changi Frankfurt per kg",
        required_columns=("origin", "destination", "usd_per_kg"),
        expect="look_elsewhere",
    )
    month = last_month(today)
    hit = Question(
        ask=(
            "Daily anchorage wait hours in Singapore for container ships, tankers and bulk carriers "
            f"in {month:%B %Y}. Budget ${BUDGET_USD}."
        ),
        need="Singapore anchorage wait hours container ship tanker bulk carrier",
        required_columns=(
            "date",
            "container_ship_avg_anchorage_wait_hours",
            "tanker_avg_anchorage_wait_hours",
            "bulk_carrier_avg_anchorage_wait_hours",
        ),
        expect="buy",
        time_start=f"{month:%Y-%m}",
        time_end=f"{month:%Y-%m}",
        reason=f"Daily Singapore anchorage waits by vessel type for {month:%B %Y}",
    )
    return miss, hit


# The seeded operating-cost table (examples/datasets, #43) covers 2024-11 to 2026-10. The story's
# founder needs today's costs across every category, not two years of one category: a custom
# slice of the latest three months of the whole table.
PORT_COSTS = Question(
    ask=(
        "I'm planning to start a port logistics company in Singapore. What does it cost to run one "
        "now: terminal handling, port dues, warehouse rent, trucking, labour and customs brokerage, "
        f"for August to October 2026? Budget ${BUDGET_USD}."
    ),
    need="Singapore port logistics operating costs",
    required_columns=("month", "cost_category", "item", "sgd_amount", "usd_amount"),
    expect="buy",
    time_start="2026-08",
    time_end="2026-10",
    reason="Current Singapore port-business operating costs to estimate a new company's running costs",
)


# --- the story ----------------------------------------------------------------------------


class Demo:
    def __init__(self, args: argparse.Namespace):
        self.args = args
        self.env_file = read_env(Path(args.env))
        self.api_url = args.api.rstrip("/")
        origins = [o.strip() for o in os.environ.get("SLIVER_ALLOWED_ORIGINS", "").split(",") if o.strip()]
        self.web_url = (origins[0] if origins else "http://127.0.0.1:5173").rstrip("/")
        self.readme = Path(args.readme)
        self.rpc_url = testnet_rpc(os.environ.get("XRPL_RPC_URL") or TESTNET_RPC_URLS[0])
        self.ledger = httpx.Client(timeout=30.0)
        # Mutations need an allowed Origin, exactly as from the web app.
        self.seller = httpx.Client(base_url=self.api_url, headers={"Origin": self.web_url}, timeout=60.0)
        self.today = datetime.now(UTC).date()
        self.run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    def secret(self, name: str) -> str:
        return os.environ.get(name) or self.env_file.get(name) or ""

    def run(self) -> None:
        say(f"Sliver demo on XRPL Testnet (run {self.run_id})")
        self.preflight()
        dataset = self.upload()
        dataset = self.wait_for_decision(dataset)
        published = self.publish(dataset)
        answers, transactions = self.buy_questions()
        balance = self.seller_view(transactions)
        self.record(dataset, published, answers, transactions, balance)

    def preflight(self) -> None:
        step(1, "Preflight: Testnet only, stack healthy, README block present")
        find_block(self.readme.read_text(encoding="utf-8"))  # fail before anything is spent
        say(f"  README.md has its {START} … {END} block")
        health = checked(self.seller.get("/api/health"), "API health check")
        say(f"  API {self.api_url}: {health.get('status')} {health.get('checks')}")
        check_directory(checked(self.seller.get("/.well-known/x402"), "x402 directory"))
        say(f"  network {TESTNET} (XRPL Testnet), ledger reads from {self.rpc_url}")
        if not self.secret("SLIVER_SELLER_PASSWORD"):
            raise DemoError(
                "SLIVER_SELLER_PASSWORD is empty. Set it in .env, run `make dev-start` and `make seed`."
            )
        if not self.secret(BUYER_SEED_VAR):
            raise DemoError(f"{BUYER_SEED_VAR} is missing from .env; run `make wallets`.")
        self.platform = self.secret(PLATFORM_ADDRESS_VAR)
        if not self.platform:
            raise DemoError(f"{PLATFORM_ADDRESS_VAR} is missing from .env; run `make wallets`.")
        say(f"  buyers pay Sliver's platform wallet {self.platform} (ADR 0005)")
        engine = (
            "Claude" if os.environ.get("ANTHROPIC_API_KEY") else "offline fallback (no ANTHROPIC_API_KEY)"
        )
        say(f"  AI review: {engine}")

    def upload(self) -> dict:
        step(2, f"Seller signs in as {DEMO_SELLER} and uploads a fresh dataset")
        account = checked(
            self.seller.post(
                "/api/auth/login",
                json={"email": DEMO_SELLER, "password": self.secret("SLIVER_SELLER_PASSWORD")},
            ),
            "Seller sign-in (check SLIVER_SELLER_PASSWORD, then `make seed`)",
        )
        self.seller_name = ((account or {}).get("user") or {}).get("display_name") or DEMO_SELLER
        generator = load_generator(Path(self.args.generator))
        data = generator.generate(self.run_id, self.today)
        title = f"Singapore anchorage waiting times, daily (demo run {self.run_id})"
        dataset = checked(
            self.seller.post(
                "/api/seller/datasets",
                data={
                    "title": title,
                    "source": "Synthetic demo data generated by `make demo`",
                    "method": f"Seeded simulation, examples/demo/generate.py (run {self.run_id})",
                    "collected_at": self.today.isoformat(),
                    "rights_confirmed": "true",
                    "rights_statement": "Synthetic data created for the Sliver demo; free to redistribute.",
                },
                files={"file": (f"singapore-anchorage-waits-{self.run_id}.csv", data, "text/csv")},
            ),
            "Upload",
        )
        say(f"  uploaded “{title}” ({dataset['size_bytes']:,} bytes)")
        say(f"  SHA-256 {dataset['sha256']}")
        say(f"  seller page: {self.web_url}/sell/datasets/{dataset['id']}")
        return dataset

    def wait_for_decision(self, dataset: dict) -> dict:
        step(3, "Acceptance pipeline (validate, profile, privacy, duplicates, AI review, ... decide)")
        shown: set[str] = set()
        deadline = time.monotonic() + PIPELINE_TIMEOUT_SECONDS
        while True:
            detail = checked(self.seller.get(f"/api/seller/datasets/{dataset['id']}"), "Dataset status")
            for item in detail["steps"]:
                if item["status"] in STEP_DONE and item["stage"] not in shown:
                    shown.add(item["stage"])
                    say(f"  {item['label']:<14} {item['status']:<8} {item.get('summary') or ''}")
            if detail["status"] in DECIDED and len(shown) == len(detail["steps"]):
                break
            if time.monotonic() > deadline:
                raise DemoError(
                    f"The pipeline did not finish in {PIPELINE_TIMEOUT_SECONDS} s; check `make logs`."
                )
            time.sleep(2)
        decision = (next((s for s in detail["steps"] if s["stage"] == "decide"), {}).get("details")) or {}
        if detail["status"] == "accepted":
            self.acceptance = f"accepted automatically (quality {decision.get('quality_score')})"
            say(f"  decision: {self.acceptance}")
            return detail
        if not reviewable(detail["status"], decision):
            raise DemoError(
                f"The dataset was not accepted (status {detail['status']}, "
                f"{len(decision.get('blocking') or [])} blocking findings). "
                f"See {self.web_url}/sell/datasets/{detail['id']}; "
                "the demo approves only an upload that missed the quality threshold."
            )
        return self.approve(detail, decision)

    def approve(self, detail: dict, decision: dict) -> dict:
        """The demo reviewer approves an upload that missed the threshold on its quality score
        alone (Claude's concerns vary between runs); never one with a blocking finding."""
        score, threshold = decision.get("quality_score"), decision.get("threshold")
        say(f"  quality {score} is below the auto-accept threshold of {threshold}, with no blocking findings")
        password = self.secret("SLIVER_REVIEWER_PASSWORD")
        if not password:
            raise DemoError("The upload needs a reviewer, but SLIVER_REVIEWER_PASSWORD is empty.")
        with httpx.Client(base_url=self.api_url, headers={"Origin": self.web_url}, timeout=60.0) as reviewer:
            checked(
                reviewer.post("/api/auth/login", json={"email": DEMO_REVIEWER, "password": password}),
                "Reviewer sign-in (check SLIVER_REVIEWER_PASSWORD, then `make seed`)",
            )
            reason = (
                f"Approved by the scripted demo reviewer (make demo): quality {score} is below the "
                f"{threshold} threshold, with no blocking findings, on synthetic demo data."
            )
            checked(
                reviewer.post(
                    f"/api/seller/datasets/{detail['id']}/review",
                    json={"decision": "approve", "reason": reason},
                ),
                "Reviewer approval",
            )
        self.acceptance = (
            f"approved by the demo reviewer (quality {score}, below the threshold of {threshold})"
        )
        say(f"  {DEMO_REVIEWER} approves it with the reason: {reason}")
        return checked(self.seller.get(f"/api/seller/datasets/{detail['id']}"), "Dataset status")

    def publish(self, dataset: dict) -> list[dict]:
        step(4, "Seller reviews the explainable valuation and publishes")
        for attempt in range(2):
            report = checked(self.seller.get(f"/api/seller/datasets/{dataset['id']}/valuation"), "Valuation")
            if not report.get("payout_ready"):
                raise DemoError(f"{DEMO_SELLER} has no XRPL payout address; run `make wallets`.")
            explanation = report.get("explanation") or {}
            say(f"  explanation by {explanation.get('source')}: {explanation.get('text', '')[:300]}")
            for sliver in report["slivers"]:
                value = sliver["valuation"]
                factors = ", ".join(f"{f['name']} ×{f['factor']}" for f in value["factors"])
                say(
                    f"  {sliver['label']:<16} {sliver['row_count']:>4} rows  suggested "
                    f"${value['suggested_price_minor'] / 100:.2f} "
                    f"(base ${value['base']['price_minor'] / 100:.2f} from {value['base']['source']}; "
                    f"{factors})"
                )
            samples = [c["row"] for c in report["sample"]["candidates"] if not c.get("problem")]
            body = {
                "suggested": {s["id"]: s["valuation"]["suggested_price_minor"] for s in report["slivers"]},
                "sample_rows": samples[:PUBLIC_SAMPLE_ROWS],
            }
            response = self.seller.post(f"/api/seller/datasets/{dataset['id']}/publish", json=body)
            if response.status_code == 409 and attempt == 0:
                say("  suggestions moved since loading (new demand or comparables); reloading")
                continue
            detail = checked(response, "Publish")
            break
        published = [r for r in detail["resources"] if r["status"] == "published"]
        say(
            f"  published {len(published)} slivers at the suggested prices; "
            f"public sample rows {body['sample_rows']}"
        )
        for resource in published:
            say(
                f"    ${resource['price_minor'] / 100:>6.2f}  {resource['title']}  "
                f"{self.web_url}/resources/{resource['id']}"
            )
        return published

    def buy_questions(self) -> tuple[list[dict], list[dict]]:
        home = Path(tempfile.mkdtemp(prefix="sliver-demo-buyer-"))
        config = Config.from_env(
            {
                "SLIVER_API_URL": self.api_url,
                "SLIVER_HOME": str(home),
                "SLIVER_XRPL_RPC_URL": self.rpc_url,
                "SLIVER_DROPS_PER_USD": os.environ.get("DROPS_PER_USD") or "",
            }
        )
        api, store = SliverApi(config.api_url), Store(config.home)
        wallet = Wallet.from_seed(self.secret(BUYER_SEED_VAR))
        self.buyer_address = wallet.address
        buyer = Buyer(config, api, store, lambda: XrplSigner(wallet, config.rpc_url, config.max_fee_drops))
        say()
        say(
            f"Buyer: the Sliver MCP's buyer code with wallet {wallet.address}, a ${BUDGET_USD} budget per "
            f"question, caps ${config.max_purchase_minor / 100:.0f} per purchase and "
            f"${config.daily_cap_minor / 100:.0f} per day. It signs locally; Sliver never sees the key."
        )
        answers = []
        for number, question in enumerate(questions(self.today), start=5):
            step(number, f"Buyer asks: {question.ask}")
            answers.append(self.ask(api, buyer, question))
        step(7, f"Buyer asks: {PORT_COSTS.ask}")
        answers.append(self.ask_for_slice(api, buyer, config.drops_per_usd, PORT_COSTS))
        return answers, [answer for answer in answers if answer["tx_hash"]]

    def search_and_evaluate(self, api: SliverApi, question: Question) -> dict:
        """sliver_search, then sliver_evaluate over the same results, as the MCP does."""
        try:
            found = api.search(q=question.need, limit=20)  # what sliver_evaluate searches
        except ApiError as error:
            raise DemoError(str(error)) from None
        listings = found.get("items", [])
        say(f"  sliver_search {question.need!r}: {found.get('total')} listings")
        report = evaluate(
            listings,
            need=question.need,
            today=self.today,
            required_columns=list(question.required_columns),
            required_terms=[],
            time_start=question.time_start,
            time_end=question.time_end,
            max_age_days=question.max_age_days,
            budget_minor=usd_to_minor(BUDGET_USD, "budget_usd"),
        )
        say(f"  sliver_evaluate → {report['recommendation']}: {report['summary']}")
        if report["recommendation"] != question.expect:
            raise DemoError(
                f"Expected {question.expect!r} for this question, got {report['recommendation']!r}."
            )
        return report

    def ask(self, api: SliverApi, buyer: Buyer, question: Question) -> dict:
        report = self.search_and_evaluate(api, question)
        best = next((c for c in report["candidates"] if c["resource_id"] == report["best"]), None)
        if best is None and report["candidates"]:
            say(
                f"    closest: “{report['candidates'][0]['title']}”: "
                f"{'; '.join(report['candidates'][0]['reasons'])}"
            )
        answer = {
            "ask": question.ask,
            "recommendation": report["recommendation"],
            "tx_hash": None,
            "title": best["title"] if best else None,
            "price_minor": None,
        }
        if report["recommendation"] != "buy":
            say("  nothing signed, nothing spent")
            return answer
        return {**answer, **self.purchase(buyer, best["resource_id"], question.reason)}

    def ask_for_slice(self, api: SliverApi, buyer: Buyer, drops_per_usd: int, question: Question) -> dict:
        """The agent-initiative story: the evaluator says the pre-cut slivers cover much more than
        the need, the agent quotes a custom slice (free, never spends), tells its human the price
        for N rows × M columns, and buys only after a yes within the human's budget."""
        report = self.search_and_evaluate(api, question)
        suggestion = report.get("custom_slice")
        if not suggestion:
            raise DemoError("sliver_evaluate suggested no custom slice for the port-costs question.")
        say(
            f"  custom slice suggested: {suggestion['title']!r}, {suggestion['time_start']} to "
            f"{suggestion['time_end']}, where {suggestion['where'] or 'every category'}"
        )
        try:
            status, body = api.quote_slice(
                suggestion["resource_id"],
                suggestion["time_start"],
                suggestion["time_end"],
                suggestion["where"],
            )
        except ApiError as error:
            raise DemoError(str(error)) from None
        budget_minor = usd_to_minor(BUDGET_USD, "budget_usd")
        quote = quote_summary(status, body, budget_minor, drops_per_usd)
        if quote["status"] != "quoted":
            raise DemoError(f"sliver_quote_slice refused ({quote.get('code')}): {quote.get('message')}")
        if quote.get("warning"):
            raise DemoError(quote["warning"])
        say(f"  sliver_quote_slice → {quote['resource_id']} (nothing spent): {quote['summary']}")
        offer = quote["summary"].split(" Nothing has been spent")[0]
        say(f"  agent to its human: “I found data worth buying. {offer} Agree?”")
        price_minor = round(quote["price_usd"] * 100)
        if not quote.get("within_budget"):
            raise DemoError(
                f"The quote ({usd(price_minor)}) is over the ${BUDGET_USD} budget; "
                "the scripted human approves only quotes within it."
            )
        say(f"  human (scripted for make demo): “Yes, buy it.” (within the ${BUDGET_USD} budget)")
        time = (quote.get("coverage") or {}).get("time") or {}
        where = (quote.get("filter") or {}).get("where") or {}
        covers = "; ".join(
            ([f"{time.get('column')} {time.get('start')} to {time.get('end')}"] if time else [])
            + [f"{column} {value}" for column, value in where.items()]
        )
        bought = self.purchase(buyer, quote["resource_id"], question.reason)
        if bought["price_minor"] != price_minor:
            raise DemoError(
                f"Bought for {usd(bought['price_minor'])}, but the quote said {usd(price_minor)}."
            )
        return {
            "ask": question.ask,
            "recommendation": report["recommendation"],
            **bought,
            "quote": {
                "rows": quote["rows"],
                "column_count": quote["column_count"],
                "parent_title": (quote.get("parent") or {}).get("title"),
                "covers": covers or "the whole table",
                "price_minor": price_minor,
                "amount_drops": int(quote["payment"]["amount_drops"]),
            },
        }

    def purchase(self, buyer: Buyer, resource_id: str, reason: str | None) -> dict:
        """sliver_buy within the budget: it pays Sliver's platform wallet, never the seller."""
        try:
            result = buyer.buy(resource_id, BUDGET_USD, reason=reason)
        except Refused as error:
            paid = (
                f" Payment {error.paid['tx_hash']} left the wallet: {error.paid['explorer_url']}"
                if error.paid
                else ""
            )
            raise DemoError(f"sliver_buy refused ({error.code}): {error.message}{paid}") from None
        if result["status"] != "delivered" or not result["sha256_verified"]:
            raise DemoError(
                f"The purchase was not delivered intact ({result['status']}): {result['explorer_url']}"
            )
        if result["pay_to"] != self.platform:
            raise DemoError(
                f"{result['tx_hash']} paid {result['pay_to']}, not Sliver's platform wallet {self.platform}."
            )
        receipt = result.get("receipt") or {}
        say(
            f"  sliver_buy → paid {result['amount_xrp']} XRP (${result['price_usd']:.2f}) "
            f"to Sliver's platform wallet {result['pay_to']}, {result['bytes']:,} bytes, "
            "SHA-256 matches the listing"
        )
        if reason:
            say(f"  agent note on the timeline: {reason}")
        say(f"  transaction {result['tx_hash']}")
        say(f"  explorer    {result['explorer_url']}")
        if receipt.get("id"):
            say(f"  timeline    {self.web_url}/purchases/{receipt['id']}")
        return {
            "tx_hash": result["tx_hash"],
            "resource_id": result["resource_id"],
            "title": result["title"],
            "price_minor": round(result["price_usd"] * 100),
            "amount_drops": round(result["amount_xrp"] * 1_000_000),
            "payer": self.buyer_address,
            "pay_to": result["pay_to"],
        }

    def seller_view(self, transactions: list[dict]) -> dict:
        """Each sale as the seller sees it: gross, Sliver's fee and the net owed at the next payout."""
        step(8, f"The seller's side: {DEMO_SELLER} on /sell/insights")
        insights = checked(self.seller.get("/api/seller/insights"), "Seller insights")
        items = {item["transaction"]["hash"].upper(): item for item in insights["earnings"]["items"]}
        balance = insights.get("balance") or {}
        for tx in transactions:
            item = items.get(tx["tx_hash"].upper())
            if item is None:
                raise DemoError(f"{tx['tx_hash']} is missing from the seller's earnings.")
            fee, net = item.get("platform_fee"), item.get("net") or {}
            if fee is None or item.get("pay_to") != self.platform:
                raise DemoError(f"{tx['tx_hash']} was not collected by Sliver's platform wallet.")
            tx["seller"] = self.seller_name
            tx["credit"] = {
                "gross_minor": item["amount"]["usd_minor"],
                "fee_bps": fee["bps"],
                "fee_minor": fee["usd_minor"],
                "net_minor": net["usd_minor"],
                "payout": (item.get("payout") or {}).get("status"),
                "next_payout_date": balance.get("next_payout_date"),
            }
            if tx["credit"]["fee_minor"] + tx["credit"]["net_minor"] != tx["credit"]["gross_minor"]:
                raise DemoError(f"{tx['tx_hash']}: Sliver's fee and the seller's net do not add up.")
            say(f"  {tx['title']}")
            say(f"    {credit_text(tx['credit'])} ({tx['credit']['payout']})")
        owed = balance.get("owed") or {}
        summary = {
            "owed_minor": owed.get("usd_minor", 0),
            "sales_owed": balance.get("sales_owed", 0),
            "next_payout_date": balance.get("next_payout_date", "?"),
        }
        say(
            f"  balance: {usd(summary['owed_minor'])} owed by Sliver across {summary['sales_owed']} sales, "
            f"next payout {summary['next_payout_date']} ({self.web_url}/sell/insights)"
        )
        return summary

    def record(
        self,
        dataset: dict,
        published: list[dict],
        answers: list[dict],
        transactions: list[dict],
        balance: dict,
    ) -> None:
        step(9, "Ledger check and README")
        if not transactions:
            raise DemoError("No transaction to record.")
        recorded = []
        for tx in transactions:
            facts = ledger_facts(read_ledger_tx(self.ledger, self.rpc_url, tx["tx_hash"]), tx["tx_hash"])
            if facts["destination"] != tx["pay_to"] or facts["delivered_drops"] != tx["amount_drops"]:
                raise DemoError(f"{tx['tx_hash']} on the ledger does not match the purchase.")
            if facts["destination"] != self.platform:
                raise DemoError(f"{tx['tx_hash']} did not pay Sliver's platform wallet {self.platform}.")
            if facts["account"] != tx["payer"]:
                raise DemoError(f"{tx['tx_hash']} was not sent by the demo buyer.")
            say(
                f"  {facts['hash']}: validated in ledger {facts['ledger_index']}, tesSUCCESS, "
                f"{xrp(facts['delivered_drops'])} XRP {facts['account']} → {facts['destination']}"
            )
            recorded.append(
                {
                    **facts,
                    "price_minor": tx["price_minor"],
                    "title": tx["title"],
                    "seller": tx["seller"],
                    "credit": tx["credit"],
                }
            )
        review = next((s for s in dataset["steps"] if s["stage"] == "ai_review"), {})
        engine = (review.get("details") or {}).get("engine")
        run = {
            "run_id": self.run_id,
            "finished_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
            "rpc_host": urlsplit(self.rpc_url).hostname,
            "transactions": recorded,
            "dataset_title": dataset["title"],
            "dataset_rows": dataset["row_count"],
            "acceptance": self.acceptance,
            "review_engine": (
                f"Claude ({(review.get('details') or {}).get('model')})"
                if engine == "claude"
                else "offline fallback"
            ),
            "published": len(published),
            "answers": answers,
            "platform_address": self.platform,
            "balance": balance,
        }
        text = self.readme.read_text(encoding="utf-8")
        updated = replace_block(text, render_block(run))
        with self.readme.open("r+", encoding="utf-8") as handle:  # in place: keeps the file's owner
            handle.write(updated)
            handle.truncate()
        say(f"  wrote {len(recorded)} transaction(s) into README.md between the demo-tx markers")
        say()
        say("Done. Open the live timeline at " + f"{self.web_url}/activity")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default="http://api:8000")
    parser.add_argument("--env", default=str(ROOT / ".env"))
    parser.add_argument("--readme", default=str(ROOT / "README.md"))
    parser.add_argument("--generator", default=str(ROOT / "examples" / "demo" / "generate.py"))
    args = parser.parse_args(argv)
    try:
        Demo(args).run()
    except DemoError as error:
        print(f"\nmake demo stopped: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
