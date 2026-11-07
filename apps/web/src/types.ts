export type User = { id: string; email: string; role: "seller" | "reviewer" };
export type Session = { user: User | null; csrf_token: string };
export type Finding = { code: string; message: string };
export type PublicProvenance = {
  source: string;
  method: string;
  collected_at: string;
  coverage: string;
};
export type Provenance = PublicProvenance & { rights_statement: string };
export type Dataset = {
  id: string;
  owner_id: string;
  title: string;
  filename: string;
  version: number;
  sha256: string;
  size_bytes: number;
  row_count: number;
  columns: string[];
  created_at: string;
  provenance: Provenance;
  validation: { valid: boolean; warnings: Finding[] };
};
export type Preview = {
  columns: string[];
  rows: string[][];
  truncated: boolean;
};
export type Resource = {
  id: string;
  dataset_id: string;
  dataset_version: number;
  owner_id: string;
  title: string;
  description: string;
  price_minor: number;
  currency: "USD";
  status: "draft" | "submitted" | "approved" | "rejected";
  review_reason: string | null;
  created_at: string;
};
export type PublicResource = Pick<
  Resource,
  | "id"
  | "title"
  | "description"
  | "price_minor"
  | "currency"
  | "dataset_version"
> & {
  row_count: number;
  columns: string[];
  provenance: PublicProvenance;
  approved_at: string;
  sha256: string;
  size_bytes: number;
  dataset_id?: string;
};

export type Marketplace = {
  mode: "disabled" | "simulated" | "xrpl-testnet";
  network: "simulation" | "xrpl:1" | null;
  quote_ttl_seconds: number;
  price_note: string;
  capabilities: Record<string, unknown>;
};
export type Quote = {
  id: string;
  resource_id: string;
  title: string;
  dataset_version: number;
  sha256: string;
  size_bytes: number;
  price_minor: number;
  currency: "USD";
  mode: Marketplace["mode"];
  network: Marketplace["network"];
  buyer_address: string | null;
  amount_drops: string | null;
  pay_to: string | null;
  memo: string;
  expires_at: string;
  status: "quoted" | "pending" | "paid" | "failed";
  transaction_hash: string | null;
  receipt_id: string | null;
  paid_at: string | null;
  download_url: string | null;
};
