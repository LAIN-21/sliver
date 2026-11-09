# Seller

Additional constraints for seller accounts, uploads and the inspection pipeline (`apps/api/sliver_api/auth`, `seller`, `pipeline`, `ai.py`, `prompts`, `slicing.py`, `security.py`, `worker.py`, the `/sell` pages in `apps/web`). Repository-wide rules in [AGENTS.md](../../AGENTS.md) still apply.

## Accounts and sessions

- Accounts are demo accounts created by `make seed`. There is no public signup. Passwords come only from the environment (`SLIVER_SELLER_PASSWORD`, `SLIVER_REVIEWER_PASSWORD`); an empty value must leave the account unable to sign in.
- Store passwords only as scrypt hashes (`auth/passwords.py`). Never log, return or persist a password or a session token. The database stores the SHA-256 of a session token, never the token.
- Session cookies stay `HttpOnly` and `SameSite=Lax`. Do not move tokens into `localStorage`, URLs or response bodies.
- Every mutation passes the Origin check in `security.py`. Do not exempt routes from it; add new browser origins through `SLIVER_ALLOWED_ORIGINS`.
- Unknown accounts and wrong passwords get the same answer.

## Uploads

- Bodies are size-checked before parsing (`BodyLimit`). Keep the 5 MiB file limit and do not read uploads fully before the size check.
- Stored dataset bytes are immutable: write each upload once under a new key and record its SHA-256. Never overwrite or edit a stored object; the worker refuses to inspect bytes whose hash no longer matches.
- Malformed form input (dates, flags, lengths) must answer 422, never 500.
- Do not block the event loop: storage, hashing and database work run in the threadpool or in sync handlers.

## Visibility

- Sellers see only their own datasets. Reviewers see only datasets that reached review (`REVIEW_STATUSES`, or decided by a reviewer). Everyone else gets 401, and datasets outside an account's view answer 404, never 403, so ids cannot be probed.
- Uploads, findings, profiles and provenance are private. Nothing here may reach public discovery; publication goes through Resources and `catalog/public.py` only.
- Duplicate findings may name the seller's own datasets or a published listing title, never another seller's private upload. Compare exact and near duplicates only against the seller's own datasets and datasets with a published Resource, so a private upload can neither be probed for nor block its owner's later upload.

## Pipeline

- Stages live in `pipeline/registry.py` and run in registry order. A stage reads the dataset and returns a `StageResult`; it must not write to the database itself. `jobs.finish` records results and dataset updates.
- Findings carry `code`, `severity` (`high` blocks, `medium` and `low` warn) and a message that names columns and row numbers. Never copy cell values into findings: privacy findings in particular must not echo the personal data they detected.
- Negative or signed numbers are data, not spreadsheet formulas. Formulas in header cells fail validation, because column names become public catalog metadata.
- Jobs are claimed only with `FOR UPDATE SKIP LOCKED` in `pipeline/jobs.py`. Do not add a queue service (see [infrastructure.md](infrastructure.md)).
- Keep `tests/test_pipeline.py`, `tests/test_seller.py`, `tests/test_auth.py` and `tests/test_ai_review.py` passing and extend them with each new stage or rule.

## AI review, packaging and the decision

- Only the column schema, the column profile and at most 20 sample rows (`ai.MAX_SAMPLE_ROWS`) may reach the model, with every cell in a privacy-flagged column, and every cell a privacy detector matches, replaced by `[redacted]`. Research sends the public listing, the schema and the time coverage, never rows. Do not add other dataset content (provenance, rights statements, owner details) to a payload.
- Never log payloads, prompts, sample rows or model output. Log the task, the dataset id and short reason codes only.
- Prompts are versioned files in `sliver_api/prompts/`. Do not edit a released prompt in place: add `<name>.v<N+1>.md` and `.schema.json` and point `ai.py` at it, so the cache (keyed by prompt version, model and dataset SHA-256) never serves answers from an older prompt.
- `ai.engine()` returns None without `ANTHROPIC_API_KEY`; every AI stage must then complete with the deterministic fallback, and tests must never reach the API.
- Validate model output before use. A slice column must pass the rules in `ai_review.choose_slice` (a non-personal category column, or a date column cut by month); public text must pass the leak guard; research sources must be URLs the web search returned.
- Public text (title, description, tags, category) may name columns and values of low-cardinality, non-personal category columns, dates and counts, never other cell values. Keep the guard in `package` as the last check before Resources are created.
- Each sliver is written once under `resources/<owner>/<dataset>/<slice>.csv` with its own SHA-256. Packaged Resources stay `draft` (accepted) or `review` (queued) and carry the placeholder price; the pipeline never publishes or prices. Only the owning seller publishes, through `seller/pricing.py`.
- `decide` uses deterministic rules only. Model output may send a dataset to a reviewer, never accept one. Keep blocking findings (any `high`, unfinished stages, `medium` privacy and near-duplicate findings, `medium` AI sensitivity concerns) out of automatic acceptance.
- Reviewer decisions need a reason, apply only to datasets in `review`, and are recorded on the dataset (`reviewed_by`, `reviewed_at`, `review_reason`).

## Valuation and publication

- `valuation.py` stays pure: no database, clock, randomness, network or model calls. Same inputs, same output. Every factor is rounded before multiplying and appears in the breakdown with its inputs, and prices are clamped to the `resources.price_minor` bounds. `seller/pricing.py` gathers the inputs.
- Claude never chooses or changes a number. It receives only the computed prices, factors and their short reasons (counts and aggregates, never rows, cell values, provenance or search texts). Its explanation is discarded for the template when it contains any number that is not in its input. Without a key, or when the call fails, the template is used; publishing never calls Claude.
- Only the owning seller sees a valuation or publishes, and only for `accepted` datasets (automatic or reviewer-approved). Other sellers get 404, reviewers 403. Prices are fixed once published; repricing is out of scope.
- Sample rows are private by default. A row becomes public only when the seller selects it at publication, at most `MAX_PUBLIC_SAMPLE_ROWS` (5), and never when it holds a value in a privacy-flagged column or a value a privacy detector matches. Candidates shown to the seller redact those cells. Keep `tests/test_valuation.py` passing.
- Earnings on the insights page are the signed-in seller's own delivered purchases only.
- `allow_custom_slices` is chosen at publication (default on) and fixed afterwards like prices. Custom slices are priced only by `valuation.custom_slice_price` from the parent's published price; they are never comparables and never appear in the seller's sliver list for publication.
