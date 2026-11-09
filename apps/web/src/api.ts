// Same-origin API client. In development Vite proxies /api to the FastAPI service.

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
    throw new ApiError(response.status, `Request failed (${response.status}).`);
  }
  return body as T;
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

export async function getHealth(signal?: AbortSignal): Promise<HealthStatus> {
  // A degraded API answers 503 with the same body, which is still useful to show.
  const body = await request<unknown>("/health", { signal });
  // Without the /api proxy (e.g. `vite preview`) the SPA fallback answers 200 with HTML.
  if (!isHealth(body)) throw new ApiError(0, "The Sliver API did not return a health report.");
  return body;
}
