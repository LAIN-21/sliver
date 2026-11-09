// Same-origin API client. In development Vite proxies /api to the FastAPI service.

import type { Account, CatalogPage, CategoryCount, PublicResource, SellerDataset, SellerDatasetDetail } from "./types";

export class ApiError extends Error {
  readonly status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, { ...init, credentials: "same-origin" });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new ApiError(0, "The Sliver API is unreachable. Check that the stack is running.");
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok && !isHealth(body)) {
    throw new ApiError(response.status, errorMessage(body) ?? `Request failed (${response.status}).`);
  }
  return body as T;
}

// FastAPI answers {"detail": "..."} or, for validation errors, {"detail": [{"loc": [...], "msg": "..."}]}.
function errorMessage(body: unknown): string | null {
  if (typeof body !== "object" || body === null || !("detail" in body)) return null;
  const { detail } = body;
  if (typeof detail === "string") return detail;
  if (!Array.isArray(detail)) return null;
  const messages = detail.flatMap((item: unknown) => {
    if (typeof item !== "object" || item === null || !("msg" in item) || typeof item.msg !== "string") return [];
    const loc = "loc" in item && Array.isArray(item.loc) ? item.loc : [];
    const field = typeof loc[loc.length - 1] === "string" ? String(loc[loc.length - 1]).replace(/_/g, " ") : "";
    return [field && field !== "body" ? `${field}: ${item.msg.replace(/^Value error, /, "")}` : item.msg];
  });
  return messages.length ? messages.join(" ") : null;
}

export type HealthStatus = {
  status: "ok" | "degraded";
  checks: Record<string, "ok" | "unavailable">;
};

function isHealth(body: unknown): body is HealthStatus {
  return (
    typeof body === "object" &&
    body !== null &&
    "status" in body &&
    (body.status === "ok" || body.status === "degraded") &&
    "checks" in body &&
    typeof body.checks === "object" &&
    body.checks !== null
  );
}

export type CatalogFilters = { q?: string; category?: string; maxPriceMinor?: number; offset?: number };

export function searchCatalog(filters: CatalogFilters, signal?: AbortSignal): Promise<CatalogPage> {
  const params = new URLSearchParams({ limit: "50" });
  if (filters.q) params.set("q", filters.q);
  if (filters.category) params.set("category", filters.category);
  if (filters.maxPriceMinor) params.set("max_price_minor", String(filters.maxPriceMinor));
  if (filters.offset) params.set("offset", String(filters.offset));
  return request<CatalogPage>(`/catalog?${params}`, { signal });
}

export async function getCategories(signal?: AbortSignal): Promise<CategoryCount[]> {
  return (await request<{ items: CategoryCount[] }>("/catalog/categories", { signal })).items;
}

export function getResource(id: string, signal?: AbortSignal): Promise<PublicResource> {
  return request<PublicResource>(`/catalog/${encodeURIComponent(id)}`, { signal });
}

export async function getHealth(signal?: AbortSignal): Promise<HealthStatus> {
  // A degraded API answers 503 with the same body, which is still useful to show.
  const body = await request<unknown>("/health", { signal });
  // Without the /api proxy (e.g. `vite preview`) the SPA fallback answers 200 with HTML.
  if (!isHealth(body)) throw new ApiError(0, "The Sliver API did not return a health report.");
  return body;
}

export async function getAccount(signal?: AbortSignal): Promise<Account | null> {
  try {
    return (await request<{ user: Account }>("/auth/me", { signal })).user;
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

export async function signIn(email: string, password: string): Promise<Account> {
  const body = JSON.stringify({ email, password });
  const init = { method: "POST", body, headers: { "Content-Type": "application/json" } };
  return (await request<{ user: Account }>("/auth/login", init)).user;
}

export async function signOut(): Promise<void> {
  await request<null>("/auth/logout", { method: "POST" });
}

export async function listDatasets(signal?: AbortSignal): Promise<SellerDataset[]> {
  return (await request<{ items: SellerDataset[] }>("/seller/datasets", { signal })).items;
}

export function getDataset(id: string, signal?: AbortSignal): Promise<SellerDatasetDetail> {
  return request<SellerDatasetDetail>(`/seller/datasets/${encodeURIComponent(id)}`, { signal });
}

export function uploadDataset(form: FormData): Promise<SellerDataset> {
  // The browser sets the multipart boundary and the Origin header the API checks.
  return request<SellerDataset>("/seller/datasets", { method: "POST", body: form });
}
