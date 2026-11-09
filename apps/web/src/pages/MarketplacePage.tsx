import { type FormEvent, useEffect, useState } from "react";
import { useSearchParams } from "react-router";

import { ApiError, getCategories, searchCatalog } from "../api";
import PageHeader, { EmptyState } from "../components/PageHeader";
import ResourceCard from "../components/ResourceCard";
import { formatCategory } from "../format";
import type { CatalogPage, CategoryCount } from "../types";

type State = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; page: CatalogPage };

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

  useEffect(() => setDraft(q), [q]);
  useEffect(() => setMaxDraft(maxUsd), [maxUsd]);

  useEffect(() => {
    const controller = new AbortController();
    getCategories(controller.signal).then(setCategories).catch(() => setCategories([]));
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    const maxPriceMinor = toPriceMinor(maxUsd);
    searchCatalog({ q, category, maxPriceMinor: maxPriceMinor || undefined }, controller.signal)
      .then((page) => setState({ kind: "ready", page }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setState({ kind: "error", message: error instanceof ApiError ? error.message : "Search failed." });
      });
    return () => controller.abort();
  }, [q, category, maxUsd]);

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
      });
      setState({ kind: "ready", page: { ...next, items: [...page.items, ...next.items] } });
    } catch (error) {
      setState({ kind: "error", message: error instanceof ApiError ? error.message : "Search failed." });
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
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    // Price applies on submit (like the query), so typing does not fire a search per keystroke.
    const minor = toPriceMinor(maxDraft);
    update({ q: draft.trim(), max: minor ? String(minor / 100) : "" });
  }

  return (
    <>
      <PageHeader title="Marketplace">
        Data that AI agents can buy by the slice. Listings show metadata only; the data itself is
        delivered after an x402 payment on the XRP Ledger.
      </PageHeader>

      <form onSubmit={submit} className="mb-6 grid gap-3 rounded-xl border border-line bg-white p-4 sm:grid-cols-[1fr_auto_auto_auto]">
        <label className="sr-only" htmlFor="q">
          Search
        </label>
        <input
          id="q"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="What does your agent need? e.g. berth waiting times in October"
          className="min-w-0 rounded-lg border border-line px-3 py-2 outline-none focus:border-brand"
        />
        <label className="sr-only" htmlFor="category">
          Category
        </label>
        <select
          id="category"
          value={category}
          onChange={(event) => update({ category: event.target.value })}
          className="rounded-lg border border-line bg-white px-3 py-2"
        >
          <option value="">All categories</option>
          {categories.map((item) => (
            <option key={item.category} value={item.category}>
              {formatCategory(item.category)} ({item.count})
            </option>
          ))}
        </select>
        <label className="sr-only" htmlFor="max">
          Maximum price in USD
        </label>
        <input
          id="max"
          inputMode="decimal"
          value={maxDraft}
          onChange={(event) => setMaxDraft(event.target.value.replace(/[^\d.]/g, ""))}
          placeholder="Max $"
          className="w-full rounded-lg border border-line px-3 py-2 sm:w-28"
        />
        <button type="submit" className="rounded-lg bg-brand px-4 py-2 font-medium text-white hover:bg-brand/90">
          Search
        </button>
      </form>

      {state.kind === "loading" ? <p className="text-muted">Loading listings…</p> : null}
      {state.kind === "error" ? <p className="text-rose-600">{state.message}</p> : null}
      {state.kind === "ready" && state.page.total === 0 ? (
        <EmptyState title="No Resources match">
          {q
            ? "Nothing in the catalog covers this yet. Searches that find nothing are shared with sellers as demand."
            : "Run `make seed` to load the demo catalog, or publish a dataset from the seller workspace."}
        </EmptyState>
      ) : null}
      {state.kind === "ready" && state.page.total > 0 ? (
        <>
          <p className="mb-3 text-sm text-muted">
            {state.page.total} {state.page.total === 1 ? "Resource" : "Resources"}
            {q ? ` matching “${q}”` : ""}
          </p>
          <ul className="grid gap-4">
            {state.page.items.map((resource) => (
              <ResourceCard key={resource.id} resource={resource} />
            ))}
          </ul>
          {state.page.items.length < state.page.total ? (
            <button
              type="button"
              onClick={showMore}
              disabled={loadingMore}
              className="mt-4 w-full rounded-lg border border-line bg-white px-4 py-2 font-medium hover:bg-surface disabled:opacity-60"
            >
              {loadingMore
                ? "Loading…"
                : `Show more (${state.page.total - state.page.items.length} remaining)`}
            </button>
          ) : null}
        </>
      ) : null}
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
