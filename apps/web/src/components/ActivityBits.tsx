import type { ReactNode } from "react";

import { EXPLORER, STEPS, type Tone } from "../activity";
import { shortHash } from "../format";
import type { StreamStatus } from "../hooks/useActivityStream";

const TONES: Record<Tone, string> = {
  good: "bg-emerald-50 text-emerald-700 ring-emerald-600/20",
  busy: "bg-brand-soft text-brand ring-brand/20",
  warn: "bg-amber-50 text-amber-800 ring-amber-600/20",
  bad: "bg-rose-50 text-rose-700 ring-rose-600/20",
  idle: "bg-surface text-muted ring-line",
};

const DOTS: Record<Tone, string> = {
  good: "bg-emerald-500",
  busy: "bg-brand",
  warn: "bg-amber-500",
  bad: "bg-rose-500",
  idle: "bg-slate-300",
};

export function StatusPill({ tone, label }: { tone: Tone; label: string }) {
  return (
    <span
      className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${TONES[tone]}`}
    >
      <span aria-hidden="true" className={`h-1.5 w-1.5 rounded-full ${DOTS[tone]} ${tone === "busy" ? "animate-pulse" : ""}`} />
      {label}
    </span>
  );
}

export function LiveBadge({ status }: { status: StreamStatus }) {
  const live = status === "live";
  return (
    <span role="status" className="inline-flex items-center gap-2 text-sm font-medium text-muted">
      <span aria-hidden="true" className="relative flex h-2.5 w-2.5">
        {live ? <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-emerald-400 opacity-75" /> : null}
        <span className={`relative inline-flex h-2.5 w-2.5 rounded-full ${live ? "bg-emerald-500" : "bg-amber-400"}`} />
      </span>
      {live ? "Live" : status === "connecting" ? "Connecting…" : "Reconnecting…"}
    </span>
  );
}

/** One segment per happy-path step; `failed` marks where a purchase stopped. */
export function StepProgress({ progress, tone }: { progress: number; tone: Tone }) {
  return (
    <div
      className="flex gap-1"
      role="img"
      aria-label={`${Math.max(progress + 1, 0)} of ${STEPS.length} purchase steps completed`}
    >
      {STEPS.map((step, index) => {
        const done = index <= progress;
        const color = !done
          ? tone === "bad" && index === progress + 1
            ? "bg-rose-400"
            : "bg-line"
          : tone === "good"
            ? "bg-emerald-500"
            : "bg-brand";
        return <span key={step.type} title={step.label} className={`h-1.5 flex-1 rounded-full transition-colors duration-500 ${color}`} />;
      })}
    </div>
  );
}

export function ExternalLink({ href, children, title }: { href: string; children: ReactNode; title?: string }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noreferrer"
      title={title}
      className="inline-flex max-w-full items-center gap-1 font-medium text-brand hover:underline"
    >
      <span className="min-w-0 [overflow-wrap:anywhere]">{children}</span>
      <svg aria-hidden="true" viewBox="0 0 16 16" className="h-3 w-3 shrink-0" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M6 3h7v7M13 3 6.5 9.5M11 9.5V13H3V5h3.5" />
      </svg>
      <span className="sr-only">(opens the XRPL Testnet explorer)</span>
    </a>
  );
}

export function TxLink({ hash, size = 6 }: { hash: string; size?: number }) {
  return (
    <ExternalLink href={`${EXPLORER}/transactions/${hash}`} title={hash}>
      <span className="font-mono">{shortHash(hash, size)}</span>
    </ExternalLink>
  );
}

export function AccountLink({ address, size = 5 }: { address: string; size?: number }) {
  return (
    <ExternalLink href={`${EXPLORER}/accounts/${address}`} title={address}>
      <span className="font-mono">{shortHash(address, size)}</span>
    </ExternalLink>
  );
}

export function LedgerLink({ index }: { index: number }) {
  return (
    <ExternalLink href={`${EXPLORER}/ledgers/${index}`}>
      <span className="font-mono">#{index.toLocaleString("en-US")}</span>
    </ExternalLink>
  );
}
