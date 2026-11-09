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
