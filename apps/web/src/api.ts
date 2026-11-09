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
  return typeof body === "object" && body !== null && "checks" in body;
}

export function getHealth(signal?: AbortSignal): Promise<HealthStatus> {
  // A degraded API answers 503 with the same body, which is still useful to show.
  return request<HealthStatus>("/health", { signal });
}
