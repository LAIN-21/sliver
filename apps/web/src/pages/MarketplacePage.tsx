import { type FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { ApiError, getCategories, searchCatalog } from "../api";
import { EmptyState } from "../components/PageHeader";
import ExchangeHero from "../components/ExchangeHero";
import ExchangeProtocol from "../components/ExchangeProtocol";
import { ExchangeIcon } from "../components/ExchangeIcons";
import RecentPurchases from "../components/RecentPurchases";
import ResourceCard from "../components/ResourceCard";
import { formatCategory } from "../format";
import type { CatalogPage, CategoryCount } from "../types";

type State =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; page: CatalogPage };

export default function MarketplacePage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q") ?? "";
  const category = params.get("category") ?? "";
  const maxUsd = params.get("max") ?? "";
  const [draft, setDraft] = useState(q);
  const [maxDraft, setMaxDraft] = useState(maxUsd);
  const [categories, setCategories] = useState<CategoryCount[]>([]);
  const [state, setState] = useState<State>({ kind: "loading" });
  const [loadingMore, setLoadingMore] = useState(false);
  const [retry, setRetry] = useState(0);

  useEffect(() => setDraft(q), [q]);
  useEffect(() => setMaxDraft(maxUsd), [maxUsd]);

  useEffect(() => {
    const controller = new AbortController();
    getCategories(controller.signal)
      .then(setCategories)
      .catch(() => setCategories([]));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    const maxPriceMinor = toPriceMinor(maxUsd);
    searchCatalog(
      { q, category, maxPriceMinor: maxPriceMinor || undefined, limit: 8 },
      controller.signal,
    )
      .then((page) => setState({ kind: "ready", page }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError")
          return;
        setState({
          kind: "error",
          message: error instanceof ApiError ? error.message : "Search failed.",
        });
      });
    return () => controller.abort();
  }, [q, category, maxUsd, retry]);

  async function showMore() {
    if (state.kind !== "ready") return;
    setLoadingMore(true);
    try {
      const page = state.page;
      const next = await searchCatalog({
        q,
        category,
        maxPriceMinor: toPriceMinor(maxUsd),
        offset: page.items.length,
        limit: 8,
      });
      setState({
        kind: "ready",
        page: { ...next, items: [...page.items, ...next.items] },
      });
    } catch (error) {
      setState({
        kind: "error",
        message: error instanceof ApiError ? error.message : "Search failed.",
      });
    } finally {
      setLoadingMore(false);
    }
  }

  function update(next: Record<string, string>) {
    const merged = new URLSearchParams(params);
    for (const [key, value] of Object.entries(next)) {
      if (value) merged.set(key, value);
      else merged.delete(key);
    }
    setParams(merged);
    document
      .getElementById("marketplace")
      ?.scrollIntoView({ block: "start", behavior: "instant" });
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    // Price applies on submit (like the query), so typing does not fire a search per keystroke.
    const minor = toPriceMinor(maxDraft);
    update({ q: draft.trim(), max: minor ? String(minor / 100) : "" });
  }

  return (
    <>
      <ExchangeHero />
      <section
        className="catalog-section"
        id="marketplace"
        aria-labelledby="marketplace-heading"
      >
        <div className="catalog-heading">
          <div>
            <p className="eyebrow">Discover your next source</p>
            <h2 id="marketplace-heading">
              The marketplace<span>.</span>
            </h2>
          </div>
          <p>
            Explore the metadata.
            <br />
            <strong>Pay only for what you need.</strong>
          </p>
        </div>
        <RecentPurchases />
        <form onSubmit={submit} className="catalog-search">
          <div className="catalog-search-query">
            <label htmlFor="q">Search</label>
            <div>
              <ExchangeIcon name="search" size={19} />
              <input
                id="q"
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                placeholder="What does your agent need?"
              />
            </div>
          </div>
          <div className="catalog-search-category">
            <label htmlFor="category">Category</label>
            <select
              id="category"
              value={category}
              onChange={(event) => update({ category: event.target.value })}
            >
              <option value="">All categories</option>
              {categories.map((item) => (
                <option key={item.category} value={item.category}>
                  {formatCategory(item.category)} ({item.count})
                </option>
              ))}
            </select>
          </div>
          <div className="catalog-search-price">
            <label htmlFor="max">
              Max price <span>(USD)</span>
            </label>
            <input
              id="max"
              inputMode="decimal"
              value={maxDraft}
              onChange={(event) =>
                setMaxDraft(event.target.value.replace(/[^\d.]/g, ""))
              }
              placeholder="No limit"
              aria-label="Maximum price in USD"
            />
          </div>
          <button
            type="submit"
            className="button-primary catalog-search-button"
          >
            Search <ExchangeIcon name="arrow" size={18} />
          </button>
        </form>

        <div className="catalog-workspace">
          <aside className="catalog-rail" aria-label="Catalog categories">
            <span className="eyebrow">Browse by category</span>
            <button
              type="button"
              onClick={() => update({ category: "" })}
              aria-pressed={!category}
              className={!category ? "is-selected" : ""}
            >
              All datasets <ExchangeIcon name="arrow" size={16} />
            </button>
            {categories.map((item) => (
              <button
                type="button"
                key={item.category}
                onClick={() => update({ category: item.category })}
                aria-pressed={category === item.category}
                className={category === item.category ? "is-selected" : ""}
              >
                <span>{formatCategory(item.category)}</span>
                <span className="category-count">{item.count}</span>
              </button>
            ))}
            <div className="catalog-rail-note">
              <ExchangeIcon name="layers" size={28} />
              <h3>
                A whole dataset.
                <br />
                Or just your part.
              </h3>
              <p>
                Custom slices let your agent quote the rows that fit. Asking for
                a quote never spends.
              </p>
              <a href="#connect-agent">
                How it works <ExchangeIcon name="arrow" size={15} />
              </a>
            </div>
          </aside>
          <div className="catalog-results" aria-busy={state.kind === "loading"}>
            <div className="results-toolbar">
              <p aria-live="polite">
                {state.kind === "ready" ? (
                  <>
                    <strong>{state.page.total}</strong>{" "}
                    {state.page.total === 1 ? "Resource" : "Resources"}
                    {q ? ` matching “${q}”` : " available"}
                  </>
                ) : state.kind === "loading" ? (
                  "Loading listings…"
                ) : (
                  "Catalog unavailable"
                )}
              </p>
              <span>
                <i />
                METADATA ONLY
              </span>
            </div>
            {state.kind === "loading" ? (
              <div className="catalog-grid skeleton-grid" aria-hidden="true">
                {[0, 1, 2, 3].map((item) => (
                  <div className="skeleton-sheet" key={item}>
                    <i />
                    <i />
                    <i />
                    <i />
                  </div>
                ))}
              </div>
            ) : null}
            {state.kind === "error" ? (
              <div className="catalog-error" role="alert">
                <ExchangeIcon name="pulse" />
                <h3>We couldn’t reach the catalog.</h3>
                <p>{state.message}</p>
                <button
                  type="button"
                  className="button-primary"
                  onClick={() => setRetry((value) => value + 1)}
                >
                  Try again <ExchangeIcon name="arrow" size={17} />
                </button>
              </div>
            ) : null}
            {state.kind === "ready" && state.page.total === 0 ? (
              <EmptyState title="No Resources match">
                {q
                  ? "Nothing in the catalog covers this yet. Searches that find nothing are shared with sellers as demand."
                  : "Run `make seed` to load the demo catalog, or publish a dataset from the seller workspace."}
              </EmptyState>
            ) : null}
            {state.kind === "ready" && state.page.total > 0 ? (
              <>
                <ul className="catalog-grid" aria-label="Resources">
                  {state.page.items.map((resource) => (
                    <ResourceCard key={resource.id} resource={resource} />
                  ))}
                </ul>
                {state.page.items.length < state.page.total ? (
                  <button
                    type="button"
                    onClick={showMore}
                    disabled={loadingMore}
                    className="catalog-more"
                  >
                    {loadingMore
                      ? "Loading…"
                      : `Show more (${state.page.total - state.page.items.length} remaining)`}
                  </button>
                ) : null}
              </>
            ) : null}
          </div>
        </div>
        <p className="catalog-disclosure">
          Listings show public metadata and seller-selected samples. Paid
          dataset contents stay private until purchase.
        </p>
      </section>
      <ExchangeProtocol />
    </>
  );
}

// The API accepts 1 cent to 1,000,000 USD (100,000,000 cents).
const MAX_PRICE_MINOR = 100_000_000;

function toPriceMinor(usd: string): number | undefined {
  const minor = Math.round(Number(usd) * 100);
  if (!Number.isFinite(minor) || minor <= 0) return undefined;
  return Math.min(minor, MAX_PRICE_MINOR);
}
