import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";

import { ApiError, getInsights } from "../api";
import { AccountLink, LiveBadge, TxLink } from "../components/ActivityBits";
import PageHeader, { EmptyState } from "../components/PageHeader";
import RequireAccount from "../components/RequireAccount";
import { formatAgo, formatAmount, formatBps, formatDateTime, formatPrice } from "../format";
import { useActivityStream, useNow } from "../hooks/useActivityStream";
import type { ActivityEvent, Money, SellerInsights } from "../types";

type State = { kind: "loading" } | { kind: "error"; message: string } | { kind: "ready"; insights: SellerInsights };

export default function InsightsPage() {
  return (
    <RequireAccount>
      {(account) =>
        account.role === "seller" ? (
          <Insights />
        ) : (
          <EmptyState title="Insights are for sellers">Sign in as a demo seller to see demand and earnings.</EmptyState>
        )
      }
    </RequireAccount>
  );
}

function Insights() {
  const [state, setState] = useState<State>({ kind: "loading" });
  // The stream starts once, from the first load's cursor; later reloads only refresh the numbers.
  const [cursor, setCursor] = useState<number | null>(null);
  // A failed live refresh keeps the last data on screen and says so, instead of replacing it.
  const [refreshError, setRefreshError] = useState<string | null>(null);
  const latest = useRef(0);
  const owned = useRef(new Set<string>());
  const loaded = useRef(false);
  const now = useNow();

  const load = useCallback((signal?: AbortSignal) => {
    const request = ++latest.current;
    getInsights(signal)
      .then((insights) => {
        if (request !== latest.current) return; // a newer reload is on its way
        owned.current = new Set(insights.resource_ids);
        loaded.current = true;
        setRefreshError(null);
        setState({ kind: "ready", insights });
        setCursor((current) => current ?? insights.cursor);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (request !== latest.current) return;
        const message = error instanceof ApiError ? error.message : "Insights could not be loaded.";
        if (loaded.current) setRefreshError(message);
        else setState({ kind: "error", message });
      });
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const onEvent = useCallback(
    (event: ActivityEvent) => {
      // A new delivery of one of this seller's slivers (a replay charges nothing new).
      if (event.type === "delivered" && event.detail !== "replay" && owned.current.has(event.resource.id)) load();
    },
    [load],
  );
  const status = useActivityStream(cursor, onEvent);

  if (state.kind === "loading") return <p className="text-muted">Loading…</p>;
  if (state.kind === "error") return <p className="text-red-700">{state.message}</p>;
  const { insights } = state;
  const { earnings, demand } = insights;
  const rate = formatBps(insights.platform_fee.bps);

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeader title="Demand and earnings">
          What buyers searched for and could not find, and what agents paid you. Buyers pay the full price straight to your
          XRPL Testnet address; Sliver never holds funds. Sliver's {rate} fee is recorded on each sale and settled with you
          off-chain.
        </PageHeader>
        <LiveBadge status={status} />
      </div>
      {refreshError ? (
        <div role="status" className="mb-6 flex flex-wrap items-center gap-3 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
          <span>Could not refresh ({refreshError}); showing the last loaded figures.</span>
          <button type="button" onClick={() => load()} className="font-medium text-brand hover:underline">
            Retry
          </button>
        </div>
      ) : null}

      <dl className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <Stat label="Paid to you (gross)" value={formatPrice(earnings.usd_minor)} hint={formatAmount(earnings.xrp_drops, "XRP")} />
        <Stat label="Net after Sliver's fee" value={formatPrice(earnings.net.usd_minor)} hint={drops(earnings.net)} />
        <Stat
          label="Fee owed to Sliver"
          value={formatPrice(earnings.fee_owed.usd_minor)}
          hint={`Current rate ${rate}. Settled off-chain; not invoiced yet.`}
        />
        <Stat
          label="Purchases delivered"
          value={earnings.purchases.toLocaleString("en-US")}
          hint={earnings.purchases_without_fee ? `${earnings.purchases_without_fee} from before the fee, no fee owed` : undefined}
        />
        <div className="min-w-0 rounded-xl border border-line bg-white p-5">
          <dt className="text-sm text-muted">Payout address</dt>
          <dd className="mt-1 font-medium">
            {insights.payout_address ? <AccountLink address={insights.payout_address} size={8} /> : "Not set (run make wallets)"}
          </dd>
        </div>
      </dl>

      <h2 className="mt-10 text-lg font-semibold">Earnings</h2>
      {earnings.items.length ? (
        <div className="mt-3 overflow-x-auto rounded-xl border border-line bg-white">
          <table className="w-full text-left text-sm">
            <thead className="bg-surface text-muted">
              <tr>
                <th className="px-3 py-2 font-medium">Settled</th>
                <th className="px-3 py-2 font-medium">Sliver</th>
                <th className="px-3 py-2 font-medium">Paid (gross)</th>
                <th className="px-3 py-2 font-medium">Sliver's fee</th>
                <th className="px-3 py-2 font-medium">Net to you</th>
                <th className="px-3 py-2 font-medium">Transaction</th>
                <th className="px-3 py-2 font-medium">
                  <span className="sr-only">Timeline</span>
                </th>
              </tr>
            </thead>
            <tbody>
              {earnings.items.map((item) => (
                <tr key={item.payment_id} className="border-t border-line">
                  <td className="px-3 py-2 whitespace-nowrap" title={item.settled_at ? formatDateTime(item.settled_at) : undefined}>
                    {item.settled_at ? formatAgo(item.settled_at, now) : "—"}
                  </td>
                  <td className="px-3 py-2 [overflow-wrap:anywhere]">
                    <Link to={`/resources/${item.resource.id}`} className="hover:underline">
                      {item.resource.title}
                    </Link>
                  </td>
                  <td className="px-3 py-2 tabular-nums whitespace-nowrap">
                    {formatPrice(item.amount.usd_minor)}{" "}
                    <span className="text-muted">({formatAmount(item.amount.value, item.amount.asset)})</span>
                  </td>
                  <td className="px-3 py-2 tabular-nums whitespace-nowrap">
                    {item.platform_fee ? (
                      <>
                        {formatPrice(item.platform_fee.usd_minor)}{" "}
                        <span className="text-muted">({formatBps(item.platform_fee.bps)})</span>
                      </>
                    ) : (
                      <span className="text-muted" title="Sold before Sliver's platform fee existed">
                        None (before fee)
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-medium tabular-nums whitespace-nowrap">{formatPrice(item.net.usd_minor)}</td>
                  <td className="px-3 py-2">
                    <TxLink hash={item.transaction.hash} />
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    <Link to={`/purchases/${item.payment_id}`} className="font-medium text-brand hover:underline">
                      Timeline
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="mt-3">
          <EmptyState title="No purchases yet">
            Publish a dataset and new purchases appear here live, each with its XRPL Testnet transaction.
          </EmptyState>
        </div>
      )}

      <h2 className="mt-10 text-lg font-semibold">Unmet buyer demand (last {demand.days} days)</h2>
      <p className="mt-1 text-sm text-muted">
        Searches that found nothing in the catalog. Matching demand raises the suggested price of your slivers.
      </p>
      {demand.items.length ? (
        <ul className="mt-3 space-y-2">
          {demand.items.map((item) => (
            <li key={item.query} className="rounded-xl border border-line bg-white p-4">
              <div className="flex flex-wrap items-baseline justify-between gap-2">
                <span className="font-medium [overflow-wrap:anywhere]">“{item.query}”</span>
                <span className="text-sm text-muted">
                  {item.unmet_searches} unmet of {item.searches} search{item.searches === 1 ? "" : "es"} · last{" "}
                  {formatAgo(item.last_seen, now)}
                </span>
              </div>
              {item.matches.length ? (
                <p className="mt-1 text-sm">
                  Matches your{" "}
                  {item.matches.map((match, index) => (
                    <span key={match.id}>
                      {index ? ", " : ""}
                      {match.status === "published" ? (
                        <Link to={`/resources/${match.id}`} className="text-brand hover:underline">
                          {match.title}
                        </Link>
                      ) : (
                        <span>
                          {match.title} <span className="text-muted">({match.status})</span>
                        </span>
                      )}
                    </span>
                  ))}
                </p>
              ) : (
                <p className="mt-1 text-sm text-muted">None of your slivers match yet.</p>
              )}
            </li>
          ))}
        </ul>
      ) : (
        <div className="mt-3">
          <EmptyState title="No unmet demand">Every recent search found something in the catalog.</EmptyState>
        </div>
      )}
    </>
  );
}

function drops(money: Money): string | undefined {
  return money.xrp_drops === null ? undefined : formatAmount(money.xrp_drops, "XRP");
}

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="min-w-0 rounded-xl border border-line bg-white p-5">
      <dt className="text-sm text-muted">{label}</dt>
      <dd className="mt-1 text-2xl font-semibold tabular-nums">{value}</dd>
      {hint ? <dd className="text-sm text-muted">{hint}</dd> : null}
    </div>
  );
}
