import type { Session } from "./types";

export class ApiError extends Error {
  status: number;
  issues: string[];
  constructor(status: number, message: string, issues: string[] = []) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.issues = issues;
  }
}

let csrfToken = "";

async function responseFor(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const method = options.method ?? "GET";
  const headers = new Headers(options.headers);
  if (method !== "GET" && method !== "HEAD") {
    if (!csrfToken)
      throw new ApiError(
        403,
        "Your session is not ready. Reload the page and try again.",
      );
    headers.set("X-CSRF-Token", csrfToken);
  }
  if (options.body && !(options.body instanceof FormData))
    headers.set("Content-Type", "application/json");
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...options,
      headers,
      credentials: "same-origin",
      cache: "no-store",
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError")
      throw error;
    throw new ApiError(
      0,
      "Sliver could not connect. Check that the local API is running, then try again.",
    );
  }
  if (!response.ok) {
    const payload: unknown = await response.json().catch(() => null);
    let message = `Request failed (${response.status}). Please try again.`;
    let issues: string[] = [];
    if (payload && typeof payload === "object" && "detail" in payload) {
      const detail = payload.detail;
      if (typeof detail === "string") message = detail;
      else if (Array.isArray(detail)) {
        issues = detail.map(
          (entry: { msg?: string }) => entry.msg ?? "A field is invalid.",
        );
        message = "Check the submitted fields.";
      } else if (detail && typeof detail === "object") {
        if ("message" in detail && typeof detail.message === "string")
          message = detail.message;
        if ("issues" in detail && Array.isArray(detail.issues)) {
          issues = detail.issues.map(
            (entry: { message?: string }) =>
              entry.message ?? "The CSV is invalid.",
          );
        }
      }
    }
    throw new ApiError(response.status, message, issues);
  }
  return response;
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const response = await responseFor(path, options);
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export async function downloadBytes(
  path: string,
  signal?: AbortSignal,
): Promise<ArrayBuffer> {
  const response = await responseFor(path, { signal });
  const maxBytes = 5 * 1024 * 1024;
  const length = response.headers.get("Content-Length");
  if (length && Number(length) > maxBytes)
    throw new Error("CSV exceeds the 5 MiB local analysis limit.");
  if (!response.body) throw new Error("The download returned no body.");
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let size = 0;
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      size += value.byteLength;
      if (size > maxBytes) {
        await reader.cancel();
        throw new Error("CSV exceeds the 5 MiB local analysis limit.");
      }
      chunks.push(value);
    }
  } finally {
    reader.releaseLock();
  }
  const bytes = new Uint8Array(size);
  let offset = 0;
  for (const chunk of chunks) {
    bytes.set(chunk, offset);
    offset += chunk.byteLength;
  }
  return bytes.buffer;
}

export async function getSession(signal?: AbortSignal): Promise<Session> {
  const session = await request<Session>("/session", { signal });
  csrfToken = session.csrf_token;
  return session;
}

export async function login(email: string, password: string): Promise<Session> {
  const session = await request<Session>("/session", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  csrfToken = session.csrf_token;
  return session;
}

export async function logout(): Promise<void> {
  await request<void>("/session", { method: "DELETE" });
  csrfToken = "";
}
