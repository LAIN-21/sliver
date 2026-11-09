# Catalog

Additional constraints for public discovery (`apps/api/sliver_api/catalog`, the marketplace pages in `apps/web`). Repository-wide rules in [AGENTS.md](../../AGENTS.md) still apply.

- Discovery must never expose protected data. Every public response goes through `catalog/public.py`, an explicit allow-list. Do not serialize models directly or add fields "for convenience".
- Never expose object keys, filenames, raw rows, owner emails, rights statements or anything that lets someone fetch stored bytes without paying.
- Sample rows become public only when a seller explicitly selects them at publication (`resources.sample_rows`, see [seller.md](seller.md)). `sample_rows` is the only row content `catalog/public.py` may expose.
- Only `published` Resources are visible. Drafts, items under review and rejected items return 404.
- Search events record what was searched, the filters and the outcome, never who searched. Do not add IP addresses, user agents or account identifiers to them.
- Keep the leak test in `apps/api/tests/test_catalog.py` passing, and extend it when the public schema grows.
- Pagination stays capped (`MAX_PAGE_SIZE`).
- Buyer-defined custom slices (`resources.parent_id` set) are unlisted: keep them out of search, categories, demand matching, valuation comparables and `GET /.well-known/x402`. They are served by id only, through the same allow-list plus `derived_from` (parent id and normalized filter).
- Custom-slice quotes (`sliver_api/slices/`) reveal counts, coverage, price and SHA-256 only, through `catalog/public.py`'s `public_quote`. Filters may use only the time column the privacy scan did not flag and low-cardinality, non-personal category columns (the leak guard's rules); never make a privacy-flagged column filterable. Keep `tests/test_custom_slices.py` passing.
