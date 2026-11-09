// How purchase activity reads in the UI: step names, outcomes and grouping by purchase.

import type { ActivityEvent, ActivityType, PurchaseStatus } from "./types";

export const EXPLORER = "https://testnet.xrpl.org";

export type Step = { type: ActivityType; label: string; hint: string };

// The happy path of one x402 purchase, in order (ADR 0004; buyers pay Sliver, ADR 0005).
export const STEPS: Step[] = [
  { type: "payment_required", label: "402 Payment Required", hint: "Sliver quoted the price and its platform XRPL address." },
  { type: "signature_received", label: "Signed payment received", hint: "The agent sent a presigned XRPL Payment in PAYMENT-SIGNATURE." },
  { type: "verified", label: "Verified by the facilitator", hint: "Signature, amount, destination and invoice binding check out." },
  { type: "integrity_checked", label: "Data integrity checked", hint: "The stored CSV matches the SHA-256 published in the listing." },
  { type: "settlement_submitted", label: "Submitted to the XRP Ledger", hint: "The facilitator submits the buyer's own transaction." },
  { type: "settled", label: "Settled", hint: "The facilitator reports the payment applied." },
  { type: "ledger_validated", label: "Validated on the ledger", hint: "Sliver re-checked the validated transaction itself." },
  { type: "delivered", label: "Data delivered", hint: "The CSV was released to the agent." },
];

const STEP_INDEX = new Map(STEPS.map((step, index) => [step.type, index]));

const OFF_PATH: Partial<Record<ActivityType, string>> = {
  rejected: "Payment rejected",
  pending: "Waiting for the ledger",
  failed: "Step failed",
};

const REASONS: Record<string, string> = {
  requirements_mismatch: "the payment changed the quoted terms",
  invoice_already_paid: "this invoice was already paid by another transaction",
  invoice_failed: "this invoice already failed",
  invoice_expired: "the quote expired",
  transaction_already_used: "that transaction already paid another invoice",
  integrity_check_failed: "the stored data failed its integrity check, so nothing was charged",
  storage_unavailable: "the data was temporarily unavailable",
  settlement_status_unknown: "the facilitator did not answer; the agent can retry the same payment",
  not_validated: "the transaction is not validated yet; the agent can retry",
  transaction_not_found: "the transaction is not on the ledger yet; the agent can retry",
  unknown_invoice: "the agent presented an unknown invoice",
  replay: "a safe retry of the same payment; nothing was charged twice",
};

export function stepIndex(type: ActivityType): number {
  return STEP_INDEX.get(type) ?? -1;
}

export function stepLabel(event: ActivityEvent): string {
  if (event.type === "delivered" && event.detail === "replay") return "Data re-delivered";
  if (event.type === "payment_required" && event.detail) return "402 Payment Required (new quote)";
  return OFF_PATH[event.type] ?? STEPS[stepIndex(event.type)]?.label ?? event.type;
}

/** A readable reason for a rejection, failure or re-issued quote. */
export function explain(detail: string | null): string | null {
  if (!detail) return null;
  if (REASONS[detail]) return REASONS[detail];
  const [code, reason] = detail.split(/:(.*)/s);
  if (code === "payment_invalid") return `the facilitator refused the payment (${reason || "unknown"})`;
  if (code === "settle_failed") return `settlement failed (${reason || "unknown"})`;
  if (code === "ledger_check") return `the ledger does not confirm the payment (${reason})`;
  return detail.replace(/_/g, " ");
}

export type Tone = "good" | "busy" | "warn" | "bad" | "idle";

export type Purchase = {
  paymentId: string;
  events: ActivityEvent[]; // oldest first
  latest: ActivityEvent;
  progress: number; // furthest happy-path step reached, -1 for none
  tone: Tone;
  status: string;
};

/** Purchase-level status from its events (the timeline page uses the server's own status). */
export function summarize(events: ActivityEvent[]): Omit<Purchase, "paymentId" | "events"> {
  const latest = events[events.length - 1];
  const progress = Math.max(...events.map((event) => stepIndex(event.type)));
  const [tone, status] = ((): [Tone, string] => {
    switch (latest.type) {
      case "delivered":
        return ["good", "Delivered"];
      case "failed":
        return ["bad", "Failed"];
      case "rejected":
        return ["bad", "Rejected"];
      case "pending":
        return ["warn", "Awaiting ledger"];
      case "payment_required":
        return ["idle", "Awaiting payment"];
      default:
        return ["busy", "In progress"];
    }
  })();
  return { latest, progress, tone, status };
}

export function statusFor(status: PurchaseStatus, events: ActivityEvent[]): { tone: Tone; label: string } {
  const summary = summarize(events);
  if (status === "delivered") return { tone: "good", label: "Delivered" };
  if (status === "failed") return { tone: "bad", label: "Failed" };
  if (status === "expired") return { tone: "idle", label: "Quote expired" };
  return { tone: summary.tone, label: summary.status };
}

/** Groups a newest-first event list into purchases, most recently active first. */
export function groupPurchases(events: ActivityEvent[]): Purchase[] {
  const byPayment = new Map<string, ActivityEvent[]>();
  for (const event of [...events].sort((a, b) => a.id - b.id)) {
    const list = byPayment.get(event.payment_id) ?? [];
    list.push(event);
    byPayment.set(event.payment_id, list);
  }
  return [...byPayment.entries()]
    .map(([paymentId, list]) => ({ paymentId, events: list, ...summarize(list) }))
    .sort((a, b) => b.latest.id - a.latest.id);
}

/** Merges new events into a newest-first list without duplicates, keeping at most `cap`. */
export function mergeEvents(current: ActivityEvent[], incoming: ActivityEvent[], cap = 300): ActivityEvent[] {
  const seen = new Set(current.map((event) => event.id));
  const fresh = incoming.filter((event) => !seen.has(event.id));
  if (fresh.length === 0) return current;
  return [...fresh, ...current].sort((a, b) => b.id - a.id).slice(0, cap);
}

export function eventTone(event: ActivityEvent): Tone {
  switch (event.type) {
    case "delivered":
    case "ledger_validated":
      return "good";
    case "failed":
    case "rejected":
      return "bad";
    case "pending":
      return "warn";
    case "payment_required":
      return "idle";
    default:
      return "busy";
  }
}
