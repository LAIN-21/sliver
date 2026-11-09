// Mirrors the public catalog schema in apps/api/sliver_api/catalog/public.py.

export type Column = { name: string; type: string };

export type Coverage = {
  time?: { column: string; start: string; end: string };
  slice?: { column: string; value: string };
};

export type PublicResource = {
  id: string;
  title: string;
  description: string;
  category: string;
  tags: string[];
  columns: Column[];
  row_count: number;
  coverage: Coverage;
  price: { amount_minor: number; currency: string };
  seller: { name: string };
  provenance: { source?: string; method?: string; collected_at?: string };
  content: { sha256: string; size_bytes: number; format: string };
  published_at: string | null;
  relevance?: number;
};

export type CatalogPage = { items: PublicResource[]; total: number; limit: number; offset: number };

export type CategoryCount = { category: string; count: number };

// Mirrors the public activity schema in apps/api/sliver_api/activity/public.py.

export type ActivityType =
  | "payment_required"
  | "signature_received"
  | "verified"
  | "rejected"
  | "integrity_checked"
  | "settlement_submitted"
  | "settled"
  | "ledger_validated"
  | "delivered"
  | "pending"
  | "failed";

export type Transaction = {
  hash: string;
  ledger_index: number | null;
  ledger_closed_at: string | null;
  explorer_url: string;
};

export type ActivityEvent = {
  id: number;
  type: ActivityType;
  at: string;
  payment_id: string;
  resource: { id: string; title: string };
  amount: { value: string; asset: string; usd_minor: number };
  network: string;
  pay_to: string;
  payer: string | null;
  transaction: Transaction | null;
  detail: string | null;
  agent_note: string | null;
};

export type ActivityFeed = { items: ActivityEvent[]; cursor: number };

export type PurchaseStatus = "required" | "settling" | "delivered" | "failed" | "expired";

export type PurchaseTimeline = {
  id: string;
  status: PurchaseStatus;
  failure_reason: string | null;
  expires_at: string | null;
  resource: { id: string; title: string };
  amount: { value: string; asset: string; usd_minor: number };
  network: string;
  pay_to: string;
  payer: string | null;
  transaction: Transaction | null;
  agent_note: string | null;
  events: ActivityEvent[];
};
