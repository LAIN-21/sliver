import { type ReactNode, useCallback, useEffect, useRef, useState } from "react";
import { Link, useParams } from "react-router";

import { eventTone, explain, STEPS, statusFor, stepIndex, stepLabel, type Tone } from "../activity";
import { ApiError, getPurchase } from "../api";
import { AccountLink, LedgerLink, LiveBadge, StatusPill, TxLink } from "../components/ActivityBits";
import { formatAmount, formatClock, formatDateTime, formatLatency, formatNetwork, formatPrice, shortHash } from "../format";
import { useActivityStream } from "../hooks/useActivityStream";
import type { ActivityEvent, PurchaseTimeline } from "../types";

type State = { kind: "loading" } | { kind: "missing" } | { kind: "error" } | { kind: "ready"; purchase: PurchaseTimeline };

export default function PurchasePage() {
  const { id = "" } = useParams();
  const [state, setState] = useState<State>({ kind: "loading" });
  // Steps already on screen when the page loaded do not animate; live ones do.
  const initial = useRef<Set<number> | null>(null);
  const [streamFrom, setStreamFrom] = useState<number | null>(null);

  // Only the newest request may update the page: each load aborts the one before it, so a slow,
  // older response (or one for the previous route id) can never overwrite newer data.
  const inflight = useRef<AbortController | null>(null);

  const load = useCallback(() => {
    inflight.current?.abort();
    const controller = new AbortController();
    inflight.current = controller;
    return getPurchase(id, controller.signal)
      .then((purchase) => {
        if (controller.signal.aborted) return;
        initial.current ??= new Set(purchase.events.map((event) => event.id));
        setStreamFrom((current) => current ?? purchase.events[purchase.events.length - 1].id);
        setState({ kind: "ready", purchase });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState((current) =>
          current.kind === "ready" ? current : error instanceof ApiError && error.status === 404 ? { kind: "missing" } : { kind: "error" },
        );
      });
  }, [id]);

  useEffect(() => {
    initial.current = null;
    setStreamFrom(null);
    setState({ kind: "loading" });
    void load();
    return () => inflight.current?.abort();
  }, [load]);

  const purchase = state.kind === "ready" ? state.purchase : null;
  const finished = purchase !== null && ["delivered", "failed", "expired"].includes(purchase.status);
  // The server's view (status, summary) is authoritative, so refetch on each new step. A finished
  // purchase has nothing left to follow, so its stream closes (a reload shows any later replay).
  const stream = useActivityStream(finished ? null : streamFrom, () => void load(), id);

  if (state.kind === "loading") return <p className="text-muted">Loading purchase…</p>;
  if (state.kind === "missing") return <Back message="No purchase with this id." />;
  if (state.kind === "error" || !purchase) return <Back message="The purchase could not be loaded." />;

  const { events } = purchase;
  const status = statusFor(purchase.status, events);
  const reached = Math.max(...events.map((event) => stepIndex(event.type)));
  const upcoming = finished || status.tone === "bad" ? [] : STEPS.slice(reached + 1);
  const signed = events.find((event) => event.type === "signature_received");
  const delivered = events.find((event) => event.type === "delivered");
  const tx = purchase.transaction;

  return (
    <article className="grid grid-cols-1 gap-8 lg:grid-cols-[minmax(0,1fr)_22rem]">
      <div className="min-w-0">
        <Link to="/activity" className="text-sm font-medium text-brand hover:underline">
          ← Activity
        </Link>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          <StatusPill tone={status.tone} label={status.label} />
          {finished ? null : <LiveBadge status={stream} />}
        </div>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight [overflow-wrap:anywhere] sm:text-3xl">
          <Link to={`/resources/${purchase.resource.id}`} className="hover:text-brand">
            {purchase.resource.title}
          </Link>
        </h1>
        <p className="mt-2 text-muted">
          <span className="font-medium tabular-nums text-ink">
            {formatPrice(purchase.amount.usd_minor)} · {formatAmount(purchase.amount.value, purchase.amount.asset)}
          </span>{" "}
          {tx ? "paid" : "payable"} straight to the seller on {formatNetwork(purchase.network)}
          {delivered && signed ? (
            <>
              . Settled and delivered{" "}
              <span className="font-medium text-ink">{formatLatency(Date.parse(delivered.at) - Date.parse(signed.at))}</span>{" "}
              after the agent signed
            </>
          ) : null}
          .
        </p>

        {purchase.agent_note ? (
          <blockquote className="mt-5 rounded-xl border border-brand/20 bg-brand-soft/60 px-4 py-3">
            <p className="text-xs font-medium uppercase tracking-wide text-brand">Agent's stated reason</p>
            <p className="mt-1 [overflow-wrap:anywhere]">“{purchase.agent_note}”</p>
          </blockquote>
        ) : null}

        <h2 className="mt-8 text-lg font-semibold">Timeline</h2>
        <ol className="mt-4">
          {events.map((event, index) => (
            <TimelineStep
              key={event.id}
              event={event}
              latency={index === 0 ? null : Date.parse(event.at) - Date.parse(events[index - 1].at)}
              animate={!initial.current?.has(event.id)}
              retry={events.slice(0, index).some((earlier) => earlier.type === event.type)}
              last={index === events.length - 1 && upcoming.length === 0}
            />
          ))}
          {upcoming.map((step, index) => (
            <Upcoming
              key={step.type}
              label={step.label}
              hint={step.hint}
              active={index === 0}
              waitingForAgent={index === 0 && reached === 0}
              last={index === upcoming.length - 1}
            />
          ))}
        </ol>
        {purchase.status === "expired" ? (
          <p className="mt-2 text-sm text-muted">The quote expired before the agent paid. Nothing was charged.</p>
        ) : null}
      </div>

      <aside className="h-fit min-w-0 rounded-xl border border-line bg-white p-5 lg:sticky lg:top-6">
        <h2 className="font-semibold">On the ledger</h2>
        <dl className="mt-3 grid gap-3 text-sm">
          <Fact label="Buyer (agent wallet)">{purchase.payer ? <AccountLink address={purchase.payer} size={8} /> : "Not known yet"}</Fact>
          <Fact label="Seller (paid directly)">
            <AccountLink address={purchase.pay_to} size={8} />
          </Fact>
          <Fact label="Transaction">{tx ? <TxLink hash={tx.hash} size={10} /> : "Not submitted yet"}</Fact>
          {tx?.ledger_index ? (
            <Fact label="Validated in ledger">
              <LedgerLink index={tx.ledger_index} />
            </Fact>
          ) : null}
          {tx?.ledger_closed_at ? <Fact label="Ledger closed">{formatDateTime(tx.ledger_closed_at)}</Fact> : null}
          <Fact label="Network">{formatNetwork(purchase.network)} (no real funds)</Fact>
        </dl>
        {purchase.status === "delivered" ? (
          <a
            href={`/api/receipts/${purchase.id}`}
            target="_blank"
            rel="noreferrer"
            className="mt-4 inline-block text-sm font-medium text-brand hover:underline"
          >
            Receipt (JSON)
          </a>
        ) : null}
        <p className="mt-4 text-xs text-muted">
          Sliver never signs or holds funds: the agent signs its own XRPL Payment and the seller receives it. Purchase{" "}
          <span className="font-mono [overflow-wrap:anywhere]">{purchase.id}</span>
        </p>
      </aside>
    </article>
  );
}

const ICON_RING: Record<Tone, string> = {
  good: "bg-emerald-500 text-white",
  busy: "bg-brand text-white",
  warn: "bg-amber-500 text-white",
  bad: "bg-rose-500 text-white",
  idle: "bg-ink text-white",
};

function TimelineStep({
  event,
  latency,
  animate,
  retry,
  last,
}: {
  event: ActivityEvent;
  latency: number | null;
  animate: boolean;
  retry: boolean;
  last: boolean;
}) {
  const tone = eventTone(event);
  const step = STEPS[stepIndex(event.type)];
  const reason = explain(event.detail);
  return (
    <li className={`relative flex gap-4 ${animate ? "animate-step-in" : ""}`}>
      <Rail last={last}>
        <span className={`flex h-7 w-7 items-center justify-center rounded-full ${ICON_RING[tone]}`}>
          <Glyph tone={tone} />
        </span>
      </Rail>
      <div className="min-w-0 flex-1 pb-6">
        <div className="flex flex-wrap items-baseline justify-between gap-x-3">
          <p className="font-medium">
            {stepLabel(event)}
            {retry && event.type === "signature_received" ? " again (retry)" : ""}
          </p>
          <p className="flex items-baseline gap-2 text-xs text-muted tabular-nums">
            {latency !== null ? (
              <span className="rounded bg-surface px-1.5 py-0.5 font-medium text-ink">+{formatLatency(latency)}</span>
            ) : null}
            <time dateTime={event.at} className="font-mono">
              {formatClock(event.at)}
            </time>
          </p>
        </div>
        <div className="mt-0.5 text-sm text-muted [overflow-wrap:anywhere]">
          <StepDetail event={event} hint={step?.hint} reason={reason} />
        </div>
      </div>
    </li>
  );
}

function StepDetail({ event, hint, reason }: { event: ActivityEvent; hint?: string; reason: string | null }) {
  switch (event.type) {
    case "payment_required":
      return (
        <>
          Asked for {formatAmount(event.amount.value, event.amount.asset)} to <AccountLink address={event.pay_to} />
          {reason ? `, after ${reason}` : ""}.
        </>
      );
    case "verified":
      return event.payer ? (
        <>
          Signed by <AccountLink address={event.payer} />. {hint}
        </>
      ) : (
        <>{hint}</>
      );
    case "integrity_checked":
      return (
        <>
          SHA-256 <span className="font-mono">{shortHash(event.detail ?? "", 8)}</span> matches the listing. Only now can money move.
        </>
      );
    case "settlement_submitted":
    case "settled":
      return event.transaction ? (
        <>
          {hint} Transaction <TxLink hash={event.transaction.hash} />
        </>
      ) : (
        <>{hint}</>
      );
    case "ledger_validated":
      return (
        <>
          {event.transaction?.ledger_index ? (
            <>
              Ledger <LedgerLink index={event.transaction.ledger_index} />
              {event.transaction.ledger_closed_at ? `, closed at ${formatClock(event.transaction.ledger_closed_at, false)}` : ""}.{" "}
            </>
          ) : null}
          Destination, exact amount and invoice binding confirmed independently of the facilitator.
        </>
      );
    default:
      return <>{reason ? `${reason[0].toUpperCase()}${reason.slice(1)}.` : hint}</>;
  }
}

function Upcoming({
  label,
  hint,
  active,
  waitingForAgent,
  last,
}: {
  label: string;
  hint: string;
  active: boolean;
  waitingForAgent: boolean;
  last: boolean;
}) {
  return (
    <li className="relative flex gap-4" aria-current={active ? "step" : undefined}>
      <Rail last={last} dashed>
        <span className="flex h-7 w-7 items-center justify-center rounded-full border-2 border-dashed border-line bg-white">
          {active ? <span className="h-3 w-3 animate-spin rounded-full border-2 border-brand border-t-transparent" /> : null}
        </span>
      </Rail>
      <div className="min-w-0 flex-1 pb-6">
        <p className={`font-medium ${active ? "text-ink" : "text-muted"}`}>{label}</p>
        <p className="mt-0.5 text-sm text-muted">{active && waitingForAgent ? "Waiting for the agent to pay." : hint}</p>
      </div>
    </li>
  );
}

function Rail({ children, last, dashed = false }: { children: ReactNode; last: boolean; dashed?: boolean }) {
  return (
    <div className="relative flex w-7 shrink-0 justify-center">
      {last ? null : (
        <span
          aria-hidden="true"
          className={`absolute top-7 bottom-0 left-1/2 -translate-x-1/2 border-l-2 ${dashed ? "border-dashed border-line" : "border-line"}`}
        />
      )}
      <span className="relative">{children}</span>
    </div>
  );
}

function Glyph({ tone }: { tone: Tone }) {
  const path = tone === "bad" ? "M5 5l6 6M11 5l-6 6" : tone === "warn" ? "M8 4.5V8l2.5 1.5" : "M4 8.5l2.5 2.5L12 5.5";
  return (
    <svg aria-hidden="true" viewBox="0 0 16 16" className="h-3.5 w-3.5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d={path} />
    </svg>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <dt className="text-muted">{label}</dt>
      <dd className="mt-0.5 font-medium [overflow-wrap:anywhere]">{children}</dd>
    </div>
  );
}

function Back({ message }: { message: string }) {
  return (
    <div>
      <p className="text-muted">{message}</p>
      <Link to="/activity" className="mt-2 inline-block font-medium text-brand hover:underline">
        Back to activity
      </Link>
    </div>
  );
}
