# Builder feedback: XRPL, x402, t54 and the XRPL AI Starter Kit

> **Draft for team review.** Every point below comes from this repository: its code, ADRs and merged pull requests. Links point to the evidence. Points marked **Team to confirm** need facts only the team has. Edit, cut or add before submission.

We built Sliver, a data marketplace where agents pay sellers per data slice with x402 v2 on XRPL Testnet. The server uses t54's `x402-xrpl` SDK and hosted facilitator from the XRPL AI Starter Kit. The buyer side is an MCP server with its own small x402 client. Before this, at SingHacks, the team built [Ledger402](https://github.com/LAIN-21/ripple-challenge), a buying agent that also paid over x402 on XRPL Testnet.

## What worked well

- **XRPL's transaction model makes independent verification simple.** After settlement, Sliver re-reads the transaction from a public Testnet RPC and checks `validated`, `tesSUCCESS`, `Destination`, `delivered_amount`, the partial-payment flag and `InvoiceID` ([`ledger_check.py`](../apps/api/sliver_api/payments/ledger_check.py)). That is enough to not trust the facilitator at all, in about 30 lines. `delivered_amount` in particular closes the partial-payment hole without extra logic.
- **`InvoiceID` binding without memos works with both facilitators.** One `PAYMENT-REQUIRED` challenge carries `extra.invoiceId`, `extra.sourceTag` and `extra.areFeesSponsored: false`. A Payment with `InvoiceID = SHA-256(invoiceId)` and no Memos settled through t54 on real Testnet runs, and the official x402.org facilitator's `/verify` returned `isValid: true` for the same requirements, and separately for a payment signed by our own client ([#23](https://github.com/LAIN-21/sliver/pull/23), [#24](https://github.com/LAIN-21/sliver/pull/24), [ADR 0004](adr/0004-x402-payments-on-xrpl.md)). Swapping facilitators is one setting (`FACILITATOR_URL`).
- **The `x402-xrpl` SDK's types and facilitator client saved real work.** `PaymentRequired`, `PaymentRequirements`, `PaymentPayload` and `FacilitatorClient` gave the server a correct x402 v2 wire format quickly ([`payments/x402.py`](../apps/api/sliver_api/payments/x402.py), [`payments/adapters.py`](../apps/api/sliver_api/payments/adapters.py)). The SDK's own buyer client (`XRPLPresignedPaymentPayer` with `invoice_binding="invoice_id"`) let `make smoke-testnet` prove the server against an independent implementation ([`payments/smoke.py`](../apps/api/sliver_api/payments/smoke.py)).
- **x402 v2 is small enough to implement independently.** Our buyer client, [`sliver-x402`](../packages/sliver-x402/README.md), parses `PAYMENT-REQUIRED`, signs with `xrpl-py` and encodes `PAYMENT-SIGNATURE` and decodes `PAYMENT-RESPONSE` in under 400 lines of Python. Its payments passed both facilitators.
- **The Testnet faucet made wallet setup one command.** `make wallets` and `sliver-mcp wallet init` create and fund Testnet wallets with no manual steps.
- **Direct-to-seller settlement keeps the marketplace non-custodial.** Because the presigned Payment goes from buyer to `payTo`, Sliver never touches funds or keys. That removed a whole class of custody and compliance design from a hackathon build ([ADR 0004](adr/0004-x402-payments-on-xrpl.md)).

## Friction and suggestions

### 1. The `x402-xrpl==0.3.4` pins ripple through the whole stack

The SDK pins `fastapi>=0.115,<0.116` and `uvicorn<0.31` ([ADR 0003](adr/0003-application-stack-and-local-containers.md), [`apps/api/pyproject.toml`](../apps/api/pyproject.toml)). Consequences we hit:

- The API is held on FastAPI 0.115.x, and its pinned Starlette emits a third-party anyio deprecation warning in our tests ([#19](https://github.com/LAIN-21/sliver/pull/19)).
- The buyer MCP couldn't use the SDK at all: `uvicorn<0.31` conflicts with the `mcp` SDK. We wrote our own client, `sliver-x402`, instead ([#24](https://github.com/LAIN-21/sliver/pull/24), [ARCHITECTURE.md](ARCHITECTURE.md)). Agent tooling is increasingly shipped as MCP servers, so other builders are likely to hit the same conflict.
- We stay on uvicorn 0.30.x. In that version an open server-sent-events connection blocked dev reloads until we added `--timeout-graceful-shutdown 3` ([#28](https://github.com/LAIN-21/sliver/pull/28), [`apps/api/Dockerfile`](../apps/api/Dockerfile)).

**Suggestion:** keep the protocol pieces (types, facilitator client, buyer signer) in a package with no web-framework dependency, and make the FastAPI middleware an optional extra (for example `x402-xrpl[fastapi]`). Loose lower bounds instead of upper pins would let both servers and MCP clients depend on it.

### 2. The official spec and t54 ask for different `extra` fields

The official `scheme_exact_xrpl.md` allows only `InvoiceID = SHA-256(invoiceId)` binding, rejects memos and expects `areFeesSponsored`. t54 requires `extra.sourceTag` ([ADR 0004](adr/0004-x402-payments-on-xrpl.md)). We send both, and it works with both facilitators, but we only found that by reading both and testing against both.

**Suggestion:** align the two, or publish one "works everywhere" requirements example in the Starter Kit, ideally with a compatibility test against both facilitators.

### 3. Memo-based invoice binding is a trap for earlier builders

Our SingHacks prototype, Ledger402, bound invoices and audit proofs with Memos. The official `exact` scheme rejects memos, so when we adapted its payment code for Sliver we dropped Memos and SendMax and switched to `InvoiceID` ([#24](https://github.com/LAIN-21/sliver/pull/24), [ADR 0004](adr/0004-x402-payments-on-xrpl.md)). The SDK's buyer client still defaults to adding a memo: in `x402-xrpl` 0.3.4, `XRPLPresignedPaymentPayerOptions.invoice_binding` accepts `"memos"`, `"invoice_id"` or `"both"`, and defaults to `"both"`. Our smoke test has to pass `invoice_binding="invoice_id"` explicitly to produce a spec-compliant payment ([`payments/smoke.py`](../apps/api/sliver_api/payments/smoke.py)).

**Suggestion:** make `invoice_id` the default in the SDK and in the Starter Kit examples, and mark memo binding as t54-specific.

### 4. Per-request pricing needs more than the static middleware

Every Sliver listing has its own price and its own seller address (`payTo`). The SDK's FastAPI path is built around a static `require_payment` configuration, so we built each challenge per listing from the SDK's types and call the facilitator client ourselves ([#23](https://github.com/LAIN-21/sliver/pull/23), [`payments/service.py`](../apps/api/sliver_api/payments/service.py)).

**Suggestion:** a middleware hook that resolves requirements per request (price, `payTo`, a fresh invoice id) would cover marketplaces and other multi-seller servers.

### 5. The hosted facilitator is best effort, with no SLA

The t54 Testnet facilitator is documented as best effort with no SLA ([ADR 0004](adr/0004-x402-payments-on-xrpl.md)). Because of that:

- CI never runs a real Testnet purchase; it uses a stub facilitator and stub ledger, and the live purchase stays a manual `make smoke-testnet` ([#23](https://github.com/LAIN-21/sliver/pull/23)).
- The server has to handle an unknown settlement outcome. A retry reconciles from the ledger instead of settling again, and a settled-but-not-yet-validated payment answers `settlement_pending` so the client retries the same payment ([`payments/service.py`](../apps/api/sliver_api/payments/service.py)).
- We give `/verify` 15 seconds (it runs while the invoice row is locked) and `/settle` 75 seconds ([`payments/adapters.py`](../apps/api/sliver_api/payments/adapters.py)). These are our guesses, not documented numbers.

**Suggestion:** publish expected latencies and a status page for the hosted facilitator, and document what `/settle` returns when the submission outcome is unknown, so servers know when to reconcile.

### 6. Ledger response shapes differ between API versions

The ledger re-check has to read transaction fields from `tx_json` (rippled API v2) or from the top level of the result (earlier versions) ([`ledger_check.py`](../apps/api/sliver_api/payments/ledger_check.py)). It is a small difference, but a security check that reads the wrong level silently sees empty fields.

**Suggestion:** a short "verify an x402 settlement yourself" recipe in the Starter Kit, with the fields to check and both response shapes.

### 7. Ledger close time is coarse

The ledger close time is rounded (resolution up to 10 seconds), so on our live timeline it can read a few seconds *after* Sliver's own "validated" timestamp ([#28](https://github.com/LAIN-21/sliver/pull/28)). Not a bug, but surprising when you show payment steps to a human.

## Team to confirm

These need facts only the team has. Add them here or delete the heading.

- How long the Starter Kit took to go from zero to the first settled Testnet payment, at SingHacks and here.
- Whether the public Testnet faucet rate-limited us during development. The MCP README warns that it can, but no PR records it happening.
- Any direct contact with t54 or the x402 maintainers (questions asked, fixes received).
- Anything from Ledger402 at SingHacks worth carrying over that isn't in this repository.
