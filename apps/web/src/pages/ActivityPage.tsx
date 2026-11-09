import { type ReactNode, useMemo, useState } from "react";
import { Link } from "react-router";

import { eventTone, explain, groupPurchases, type Purchase, stepLabel } from "../activity";
import { AccountLink, LiveBadge, StatusPill, StepProgress, TxLink } from "../components/ActivityBits";
import PageHeader, { EmptyState } from "../components/PageHeader";
import { formatAgo, formatAmount, formatClock, formatPrice } from "../format";
import { useActivityFeed } from "../hooks/useActivityFeed";
import { useNow } from "../hooks/useActivityStream";
import type { ActivityEvent } from "../types";

const DOT = { good: "bg-emerald-500", busy: "bg-brand", warn: "bg-amber-500", bad: "bg-rose-500", idle: "bg-slate-300" };

export default function ActivityPage() {
  const feed = useActivityFeed(200);
  const now = useNow();
  const [paidOnly, setPaidOnly] = useState(false);
  const purchases = useMemo(() => {
    const all = groupPurchases(feed.events);
    return paidOnly ? all.filter((purchase) => purchase.progress > 0) : all;
  }, [feed.events, paidOnly]);

  return (
    <>
      <div className="flex flex-wrap items-start justify-between gap-x-6">
        <PageHeader title="Activity">
          Every agent purchase as it happens: the HTTP 402 quote, the signed payment, verification, settlement and
          validation on the XRP Ledger Testnet, then delivery.
        </PageHeader>
        <div className="mb-6 sm:mt-2">
          <LiveBadge status={feed.status} />
        </div>
      </div>

      {feed.error ? <p className="text-rose-600">{feed.error}</p> : null}
      {feed.loading ? <p className="text-muted">Loading activity…</p> : null}
      {!feed.loading && !feed.error && feed.events.length === 0 ? (
        <EmptyState title="No purchases yet">
          Purchases appear here live. Try <code className="font-mono">make smoke-testnet</code>, or ask an agent with
          the Sliver MCP to buy a slice.
        </EmptyState>
      ) : null}

      {feed.events.length > 0 ? (
        <div className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <section aria-labelledby="purchases-heading" className="min-w-0">
            <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
              <h2 id="purchases-heading" className="text-lg font-semibold">
                Purchases
              </h2>
              <label className="flex items-center gap-2 text-sm text-muted">
                <input
                  type="checkbox"
                  checked={paidOnly}
                  onChange={(event) => setPaidOnly(event.target.checked)}
                  className="h-4 w-4 accent-brand"
                />
                Hide unpaid quotes
              </label>
            </div>
            {purchases.length === 0 ? (
              <EmptyState title="Only unpaid quotes so far">Clear the filter to see agents asking for prices.</EmptyState>
            ) : (
              <ul className="grid gap-3">
                {purchases.map((purchase) => (
                  <PurchaseCard key={purchase.paymentId} purchase={purchase} now={now} />
                ))}
              </ul>
            )}
          </section>

          <aside aria-labelledby="stream-heading" className="min-w-0">
            <h2 id="stream-heading" className="mb-3 text-lg font-semibold">
              Event stream
            </h2>
            <ol className="overflow-hidden rounded-xl border border-line bg-white">
              {feed.events.slice(0, 30).map((event) => (
                <EventLine key={event.id} event={event} />
              ))}
            </ol>
          </aside>
        </div>
      ) : null}
    </>
  );
}

function PurchaseCard({ purchase, now }: { purchase: Purchase; now: number }) {
  const { latest } = purchase;
  const first = purchase.events[0];
  const note = purchase.events.find((event) => event.agent_note)?.agent_note;
  const tx = [...purchase.events].reverse().find((event) => event.transaction)?.transaction;
  const payer = [...purchase.events].reverse().find((event) => event.payer)?.payer;
  const reason = latest.type === "delivered" ? null : explain(latest.detail);
  const timeline = `/purchases/${purchase.paymentId}`;

  return (
    <li className="animate-step-in rounded-xl border border-line bg-white p-4 transition hover:border-brand/40 hover:shadow-sm sm:p-5">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <StatusPill tone={purchase.tone} label={purchase.status} />
        <time dateTime={latest.at} className="text-xs text-muted">
          {formatAgo(latest.at, now)}
        </time>
      </div>
      <h3 className="mt-2 font-semibold [overflow-wrap:anywhere]">
        <Link to={timeline} className="hover:text-brand">
          {first.resource.title}
        </Link>
      </h3>
      {note ? (
        <p className="mt-1 text-sm text-muted [overflow-wrap:anywhere]">
          <span className="font-medium text-ink">Agent:</span> “{note}”
        </p>
      ) : null}
      <div className="mt-3">
        <StepProgress progress={purchase.progress} tone={purchase.tone} />
        <p key={latest.id} className="animate-step-in mt-1.5 text-xs text-muted [overflow-wrap:anywhere]">
          {stepLabel(latest)}
          {reason ? `: ${reason}` : ""}
        </p>
      </div>
      <dl className="mt-3 flex flex-wrap gap-x-5 gap-y-1 text-sm">
        <Meta label="Price">
          <span className="tabular-nums">
            {formatPrice(first.amount.usd_minor)} · {formatAmount(first.amount.value, first.amount.asset)}
          </span>
        </Meta>
        {payer ? (
          <Meta label="Buyer">
            <AccountLink address={payer} size={4} />
          </Meta>
        ) : null}
        <Meta label="Seller">
          <AccountLink address={first.pay_to} size={4} />
        </Meta>
        {tx ? (
          <Meta label="Tx">
            <TxLink hash={tx.hash} size={5} />
          </Meta>
        ) : null}
      </dl>
      <Link to={timeline} className="mt-3 inline-block text-sm font-medium text-brand hover:underline">
        View timeline →
      </Link>
    </li>
  );
}

function Meta({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex min-w-0 gap-1.5">
      <dt className="text-muted">{label}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function EventLine({ event }: { event: ActivityEvent }) {
  return (
    <li className="animate-step-in border-t border-line first:border-t-0">
      <Link to={`/purchases/${event.payment_id}`} className="flex gap-3 px-4 py-2.5 hover:bg-surface">
        <span aria-hidden="true" className={`mt-1.5 h-2 w-2 shrink-0 rounded-full ${DOT[eventTone(event)]}`} />
        <span className="min-w-0 flex-1">
          <span className="block text-sm font-medium">{stepLabel(event)}</span>
          <span className="block truncate text-xs text-muted">{event.resource.title}</span>
        </span>
        <time dateTime={event.at} className="shrink-0 font-mono text-xs text-muted tabular-nums">
          {formatClock(event.at).slice(0, 8)}
        </time>
      </Link>
    </li>
  );
}
