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
  // Rows the seller chose to make public when publishing (empty unless they selected some).
  sample_rows: string[][];
  published_at: string | null;
  relevance?: number;
};

export type CatalogPage = { items: PublicResource[]; total: number; limit: number; offset: number };

export type CategoryCount = { category: string; count: number };

// Private seller and reviewer views, mirroring apps/api/sliver_api/seller/uploads.py.

export type Account = { id: string; email: string; display_name: string; role: "seller" | "reviewer" };

export type StepStatus = "pending" | "running" | "passed" | "warning" | "failed" | "skipped";

export type DatasetStatus = "queued" | "inspecting" | "review" | "rejected" | "accepted" | "published";

export type Finding = {
  code: string;
  severity: "high" | "medium" | "low";
  message: string;
  column?: string;
  rows?: number[];
  count?: number;
  matched_dataset?: string;
};

export type StepSummary = {
  stage: string;
  label: string;
  status: StepStatus;
  summary: string | null;
  finding_count: number;
};

export type StepDetail = StepSummary & {
  findings: Finding[];
  details: Record<string, unknown>;
  error: string | null;
  attempts: number;
  started_at: string | null;
  finished_at: string | null;
};

export type SellerDataset = {
  id: string;
  title: string;
  filename: string;
  status: DatasetStatus;
  sha256: string;
  size_bytes: number;
  row_count: number;
  created_at: string;
  steps: StepSummary[];
};

export type ColumnProfile = {
  name: string;
  type: string;
  null_count: number;
  null_pct: number;
  distinct: number;
  min?: number | string;
  max?: number | string;
  mean?: number;
  min_length?: number;
  max_length?: number;
};

// A packaged sliver as its seller and the reviewer see it (a draft until the seller publishes it).
export type PackagedResource = {
  id: string;
  title: string;
  description: string;
  category: string;
  tags: string[];
  row_count: number;
  coverage: Coverage;
  slice: { column: string; period: "month" | null; value: string } | null;
  sha256: string;
  size_bytes: number;
  status: "draft" | "review" | "published" | "rejected";
  price_minor: number | null;
  published_at: string | null;
  sample_rows: number;
};

export type ReviewOutcome = {
  decision: "approved" | "rejected";
  reason: string;
  reviewer: string | null;
  decided_at: string;
};

export type Listing = { title: string; description: string; category: string; tags: string[] };

export type AiReviewDetails = {
  engine: "claude" | "fallback";
  model?: string;
  cached?: boolean;
  fallback_reason?: string;
  listing?: Listing;
  slice?: { column: string; period: "value" | "month" | "none"; source: "claude" | "rule" | "none" };
};

export type DecisionDetails = {
  decision: "accepted" | "review";
  quality_score: number;
  threshold: number;
  blocking: { stage: string; code: string; message: string }[];
  deductions: { stage: string; code: string; message: string; points: number }[];
};

export type ResearchSource = { url: string; title: string; note: string };

export type SellerDatasetDetail = Omit<SellerDataset, "steps"> & {
  steps: StepDetail[];
  columns: Column[];
  provenance: {
    source: string;
    method: string;
    collected_at: string;
    rights_confirmed: boolean;
    rights_confirmed_at: string;
    rights_statement?: string;
  };
  seller: { name: string };
  resources: PackagedResource[];
  review: ReviewOutcome | null;
};

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

// Valuation and publication, mirroring apps/api/sliver_api/valuation.py and seller/pricing.py.

export type ValuationFactor = {
  name: "quality" | "uniqueness" | "demand" | "public_availability" | "coverage";
  label: string;
  factor: number;
  inputs: Record<string, unknown>;
  reason: string;
};

export type Valuation = {
  suggested_price_minor: number;
  range: { low_price_minor: number; high_price_minor: number };
  base: { price_minor: number; source: "comparables" | "category"; inputs: Record<string, unknown> };
  factors: ValuationFactor[];
};

export type SliverValuation = {
  id: string;
  title: string;
  label: string;
  row_count: number;
  status: PackagedResource["status"];
  valuation: Valuation | null;
  price_minor?: number;
  accepted_suggestion?: boolean | null;
  published_at?: string | null;
  sample_rows?: number;
};

export type Explanation = { text: string; source: "claude" | "template"; model?: string; reason?: string };

export type SampleCandidate = { row: number; values: string[]; problem: string | null };

export type ValuationReport = {
  dataset_id: string;
  status: DatasetStatus;
  publishable: boolean;
  payout_ready: boolean;
  explanation: Explanation | null;
  slivers: SliverValuation[];
  sample: { max_rows: number; selected: number[]; header: string[]; candidates: SampleCandidate[] };
};

export type DemandItem = {
  query: string;
  searches: number;
  unmet_searches: number;
  last_seen: string;
  matches: { id: string; title: string; status: PackagedResource["status"] }[];
};

export type Earning = {
  payment_id: string;
  resource: { id: string; title: string };
  amount: { value: string; asset: string; usd_minor: number };
  network: string;
  payer: string | null;
  settled_at: string | null;
  transaction: { hash: string; ledger_index: number | null; explorer_url: string };
};

export type SellerInsights = {
  cursor: number;
  resource_ids: string[];
  payout_address: string | null;
  earnings: { purchases: number; usd_minor: number; xrp_drops: string; items: Earning[] };
  demand: { days: number; items: DemandItem[] };
};
