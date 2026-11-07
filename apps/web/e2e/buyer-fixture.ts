import { expect } from "@playwright/test";
import type { APIRequestContext, PlaywrightWorkerArgs } from "@playwright/test";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export const origin = "http://127.0.0.1:5173";
export const syntheticCSV = readFileSync(
  fileURLToPath(new URL("../../../examples/fixtures/synthetic-routes.csv", import.meta.url)),
);

export type BuyerOffer = { id: string; title: string; sha256: string; sizeBytes: number };

function password(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Set ${name} to the API seed password.`);
  return value;
}

async function login(context: APIRequestContext, email: string, secret: string) {
  const response = await context.get("/api/session");
  expect(response.status()).toBe(200);
  const session = await response.json() as { csrf_token: string };
  const loggedIn = await context.post("/api/session", {
    headers: { Origin: origin, "X-CSRF-Token": session.csrf_token },
    data: { email, password: secret },
  });
  expect(loggedIn.status()).toBe(200);
  const authenticated = await loggedIn.json() as { csrf_token: string };
  return { Origin: origin, "X-CSRF-Token": authenticated.csrf_token };
}

/** Seed through real seller/reviewer boundaries, never through a private test API. */
export async function approvedOffer(
  playwright: PlaywrightWorkerArgs["playwright"],
  title: string,
  priceMinor = 300,
): Promise<BuyerOffer> {
  const seller = await playwright.request.newContext({ baseURL: origin });
  const reviewer = await playwright.request.newContext({ baseURL: origin });
  try {
    const sellerHeaders = await login(seller, "seller-a@sliver.local", password("SLIVER_SELLER_A_PASSWORD"));
    const upload = await seller.post("/api/datasets", {
      headers: sellerHeaders,
      multipart: {
        title,
        provenance: JSON.stringify({
          source: "SYNTHETIC route observations; no production or private data",
          method: "Deterministic local demonstration fixture",
          collected_at: "2026-11-07",
          coverage: "Singapore-Jakarta and Singapore-Port Klang, 2026-11-01 to 2026-11-07",
          rights_statement: "Wholly synthetic demo data created for this test. No third-party private data.",
        }),
        file: { name: "synthetic-routes.csv", mimeType: "text/csv", buffer: syntheticCSV },
      },
    });
    expect(upload.status()).toBe(201);
    const dataset = await upload.json() as { id: string };
    const created = await seller.post("/api/resources", {
      headers: sellerHeaders,
      data: { dataset_id: dataset.id, title, description: "Synthetic logistics observations for client-side route comparison.", price_minor: priceMinor, currency: "USD" },
    });
    expect(created.status()).toBe(201);
    const resource = await created.json() as { id: string };
    const submitted = await seller.post(`/api/resources/${resource.id}/submit`, { headers: sellerHeaders });
    expect(submitted.status()).toBe(200);
    const reviewerHeaders = await login(reviewer, "reviewer@sliver.local", password("SLIVER_REVIEWER_PASSWORD"));
    const reviewed = await reviewer.post(`/api/resources/${resource.id}/review`, {
      headers: reviewerHeaders,
      data: { decision: "approve", reason: "Reviewed synthetic source, schema and demonstration rights." },
    });
    expect(reviewed.status()).toBe(200);
    return { id: resource.id, title, sha256: createHash("sha256").update(syntheticCSV).digest("hex"), sizeBytes: syntheticCSV.length };
  } finally {
    await seller.dispose();
    await reviewer.dispose();
  }
}
