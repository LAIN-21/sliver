import { test, expect } from "@playwright/test";
import type { APIRequestContext } from "@playwright/test";
import { createHash } from "node:crypto";
import { approvedOffer, origin, syntheticCSV } from "./buyer-fixture";

type Quote = {
  id: string;
  status: string;
  mode: string;
  sha256: string;
  size_bytes: number;
  receipt_id: string | null;
  transaction_hash: string | null;
};

/** Bounded correctness exercise; these timings are not a throughput benchmark. */
async function bounded<T, R>(items: T[], visit: (item: T) => Promise<R>): Promise<R[]> {
  const results = new Array<R>(items.length);
  let next = 0;
  await Promise.all(Array.from({ length: Math.min(20, items.length) }, async () => {
    while (next < items.length) {
      const index = next++;
      results[index] = await visit(items[index]);
    }
  }));
  return results;
}

test("bounded concurrent purchases preserve one receipt, exact bytes and session isolation", async ({ playwright }, testInfo) => {
  const offer = await approvedOffer(playwright, `Synthetic concurrency fixture ${Date.now()}`);
  const owner = await playwright.request.newContext({ baseURL: origin });
  const outsider = await playwright.request.newContext({ baseURL: origin });
  try {
    const marketplace = await owner.get("/api/marketplace");
    expect(marketplace.status()).toBe(200);
    expect((await marketplace.json() as { mode: string }).mode).toBe("simulated");

    async function anonymousHeaders(context: APIRequestContext) {
      const response = await context.get("/api/session");
      expect(response.status()).toBe(200);
      const session = await response.json() as { csrf_token: string; user: unknown };
      expect(session.user).toBeNull();
      return { Origin: origin, "X-CSRF-Token": session.csrf_token };
    }
    const ownerHeaders = await anonymousHeaders(owner);
    const outsiderHeaders = await anonymousHeaders(outsider);

    async function quote(): Promise<Quote> {
      const response = await owner.post("/api/quotes", {
        headers: ownerHeaders, data: { resource_id: offer.id },
      });
      expect(response.status()).toBe(201);
      const result = await response.json() as Quote;
      expect(result.sha256).toBe(offer.sha256);
      expect(result.size_bytes).toBe(offer.sizeBytes);
      expect(result.status).toBe("quoted");
      return result;
    }

    async function confirm(selected: Quote): Promise<Quote> {
      const response = await owner.post(`/api/quotes/${selected.id}/confirm`, {
        headers: ownerHeaders, data: {},
      });
      expect(response.status()).toBe(200);
      const result = await response.json() as Quote;
      expect(result.status).toBe("paid");
      expect(result.mode).toBe("simulated");
      expect(result.receipt_id).toMatch(/^SIM-/);
      expect(result.transaction_hash).toBeNull();
      return result;
    }

    async function download(selected: Quote) {
      const response = await owner.get(`/api/quotes/${selected.id}/download`);
      expect(response.status()).toBe(200);
      expect(response.headers()["cache-control"]).toBe("no-store");
      const bytes = await response.body();
      expect(bytes.length).toBe(selected.size_bytes);
      expect(bytes.equals(syntheticCSV)).toBeTruthy();
      expect(createHash("sha256").update(bytes).digest("hex")).toBe(selected.sha256);
    }

    const paid = await confirm(await quote());
    const unpaid = await quote();
    const created: Quote[] = [];
    const repeatedReceipts: Array<string | null> = [];
    // Forty operations share one session, exercising catalog reads, independent
    // quote creation, repeated settlement and private delivery concurrently.
    await bounded(Array.from({ length: 40 }, (_, index) => index), async (index) => {
      if (index < 8) {
        const response = await owner.get("/api/catalog", { params: { q: offer.title, limit: 50 } });
        expect(response.status()).toBe(200);
        const catalog = await response.json() as { items: Array<{ id: string }> };
        expect(catalog.items.some((item) => item.id === offer.id)).toBeTruthy();
      } else if (index < 16) {
        created.push(await quote());
      } else if (index < 28) {
        repeatedReceipts.push((await confirm(paid)).receipt_id);
      } else {
        await download(paid);
      }
    });
    expect(created).toHaveLength(8);
    expect(new Set(created.map((item) => item.id)).size).toBe(8);
    expect(new Set(repeatedReceipts)).toEqual(new Set([paid.receipt_id]));

    const settlements = await bounded(Array.from({ length: 24 }, (_, index) => created[Math.floor(index / 3)]), confirm);
    const receiptSets = new Map(created.map((item) => [item.id, new Set<string | null>()]));
    for (const settled of settlements) receiptSets.get(settled.id)!.add(settled.receipt_id);
    for (const receipts of receiptSets.values()) expect(receipts.size).toBe(1);
    expect(new Set(settlements.map((item) => item.receipt_id)).size).toBe(8);
    await bounded(created, download);

    await bounded(Array.from({ length: 12 }, (_, index) => index), async (index) => {
      if (index % 4 === 0) {
        expect((await owner.get(`/api/quotes/${unpaid.id}/download`)).status()).toBe(402);
      } else if (index % 4 === 1) {
        expect((await outsider.get(`/api/quotes/${paid.id}/download`)).status()).toBe(404);
      } else if (index % 4 === 2) {
        expect((await outsider.post(`/api/quotes/${paid.id}/confirm`, {
          headers: outsiderHeaders, data: {},
        })).status()).toBe(404);
      } else {
        expect((await owner.post(`/api/quotes/${paid.id}/confirm`, {
          headers: { Origin: origin }, data: {},
        })).status()).toBe(403);
      }
    });

    await testInfo.attach("bounded-transaction-concurrency", {
      contentType: "application/json",
      body: JSON.stringify({
        result: "passed", scope: "Bounded correctness verification against the configured API stack; no throughput claim",
        max_concurrent_operations: 20, mixed_batch_operations: 40, new_quotes: 8,
        confirmations_per_new_quote: 3, repeated_paid_confirmations: 12,
        exact_digest_and_size_downloads: 20, double_receipts: 0,
        access_guards: { unpaid: 402, other_session: 404, missing_csrf: 403 },
        mode: "simulated", real_payments: 0,
      }, null, 2),
    });
  } finally {
    await owner.dispose();
    await outsider.dispose();
  }
});
