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
  // Custom slices are created after this page loads: a delivery of an unknown sliver reloads once,
  // and the reload says whether it is this seller's.
  const foreign = useRef(new Set<string>());
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
      if (event.type !== "delivered" || event.detail === "replay") return;
      const id = event.resource.id;
      if (owned.current.has(id)) load();
      else if (!foreign.current.has(id)) {
        foreign.current.add(id);
        load();
      }
    },
    [load],
  );
  const status = useActivityStream(cursor, onEvent);

  if (state.kind === "loading") return <p className="text-muted">Loading…</p>;
  if (state.kind === "error") return <p className="text-red-700">{state.message}</p>;
  const { insights } = state;
  const { earnings, demand, balance } = insights;
  const rate = formatBps(insights.platform_fee.bps);

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-4">
        <PageHeader title="Balance, earnings and demand">
          What Sliver owes you, what agents bought, and what buyers searched for and could not find. Buyers pay Sliver's
          platform wallet on the XRPL Testnet; Sliver keeps its {rate} fee and pays you the rest every 15 days.
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

      <section aria-labelledby="balance" className="rounded-xl border border-brand/20 bg-brand-soft/40 p-5">
        <h2 id="balance" className="text-lg font-semibold">
          Balance
        </h2>
        <dl className="mt-3 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <Stat
            label="Sliver owes you"
            value={formatPrice(balance.owed.usd_minor)}
            hint={`${drops(balance.owed) ?? ""} · ${balance.sales_owed} sale${balance.sales_owed === 1 ? "" : "s"} not paid out yet`}
          />
          <Stat label="Next payout" value={formatPayoutDate(balance.next_payout_date)} hint={`Payouts run on the ${balance.schedule}.`} />
          <div className="min-w-0 rounded-xl border border-line bg-white p-5">
            <dt className="text-sm text-muted">Payout address</dt>
            <dd className="mt-1 font-medium">
              {insights.payout_address ? <AccountLink address={insights.payout_address} size={8} /> : "Not set (run make wallets)"}
            </dd>
          </div>
        </dl>
        <h3 className="mt-5 font-medium">Payout history</h3>
        {balance.payouts.length ? (
          <ul className="mt-2 space-y-1 text-sm">
            {balance.payouts.map((payout) => (
              <li key={payout.paid_out_at} className="tabular-nums">
                {formatDateTime(payout.paid_out_at)}: {formatPrice(payout.usd_minor)} for {payout.sales} sale
                {payout.sales === 1 ? "" : "s"}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-1 text-sm text-muted">
            No payouts yet. Payouts are not automated in this demo; your balance is paid to your payout address.
          </p>
        )}
      </section>

      <dl className="mt-6 grid gap-4 sm:grid-cols-3">
        <Stat label="Paid by buyers (gross)" value={formatPrice(earnings.usd_minor)} hint={formatAmount(earnings.xrp_drops, "XRP")} />
        <Stat label="Sliver's fee" value={formatPrice(earnings.platform_fee.usd_minor)} hint={`Current rate ${rate}`} />
        <Stat
          label="Your net"
          value={formatPrice(earnings.net.usd_minor)}
          hint={`${earnings.purchases} purchase${earnings.purchases === 1 ? "" : "s"}${
            earnings.direct_purchases ? `, ${earnings.direct_purchases} paid to you directly before Sliver collected` : ""
          }`}
        />
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
                <th className="px-3 py-2 font-medium">Payout</th>
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
                    {item.resource.custom_slice_of ? (
                      <span className="ml-2 rounded bg-surface px-1.5 py-0.5 text-xs font-medium text-muted">
                        custom slice
                      </span>
                    ) : null}
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
                      <span className="text-muted" title="Paid straight to you before Sliver collected payments">
                        None (paid to you)
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 font-medium tabular-nums whitespace-nowrap">{formatPrice(item.net.usd_minor)}</td>
                  <td className="px-3 py-2 whitespace-nowrap">
                    {item.payout.status === "owed" ? (
                      <span className="text-amber-800">Owed, {formatPayoutDate(balance.next_payout_date)}</span>
                    ) : item.payout.status === "paid" ? (
                      <span className="text-emerald-700">Paid {item.payout.paid_out_at ? formatAgo(item.payout.paid_out_at, now) : ""}</span>
                    ) : (
                      <span className="text-muted">Paid directly</span>
                    )}
                  </td>
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

function formatPayoutDate(isoDate: string): string {
  return new Date(`${isoDate}T00:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" });
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
