# Seller

Additional constraints for seller accounts, uploads and the inspection pipeline (`apps/api/sliver_api/auth`, `seller`, `pipeline`, `security.py`, `worker.py`, the `/sell` pages in `apps/web`). Repository-wide rules in [AGENTS.md](../../AGENTS.md) still apply.

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

- Sellers see only their own datasets. Reviewers see only datasets that reached review (`REVIEW_STATUSES`). Everyone else gets 401, and datasets outside an account's view answer 404, never 403, so ids cannot be probed.
- Uploads, findings, profiles and provenance are private. Nothing here may reach public discovery; publication goes through Resources and `catalog/public.py` only.
- Duplicate findings may name the seller's own datasets or a published listing title, never another seller's private upload. Compare exact and near duplicates only against the seller's own datasets and datasets with a published Resource, so a private upload can neither be probed for nor block its owner's later upload.

## Pipeline

- Stages live in `pipeline/registry.py` and run in registry order. A stage reads the dataset and returns a `StageResult`; it must not write to the database itself. `jobs.finish` records results and dataset updates.
- Findings carry `code`, `severity` (`high` blocks, `medium` and `low` warn) and a message that names columns and row numbers. Never copy cell values into findings: privacy findings in particular must not echo the personal data they detected.
- Negative or signed numbers are data, not spreadsheet formulas. Formulas in header cells fail validation, because column names become public catalog metadata.
- Jobs are claimed only with `FOR UPDATE SKIP LOCKED` in `pipeline/jobs.py`. Do not add a queue service (see [infrastructure.md](infrastructure.md)).
- Keep `tests/test_pipeline.py`, `tests/test_seller.py` and `tests/test_auth.py` passing and extend them with each new stage or rule.
