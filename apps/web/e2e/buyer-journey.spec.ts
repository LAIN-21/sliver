import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { createHash } from "node:crypto";
import { approvedOffer, origin, syntheticCSV } from "./buyer-fixture";
import type { BuyerOffer } from "./buyer-fixture";

let offer: BuyerOffer;

test.beforeAll(async ({ playwright }) => {
  offer = await approvedOffer(playwright, `Synthetic buyer routes ${Date.now()}`);
});

async function chooseOffer(page: Page) {
  await page.goto("/");
  await page.getByRole("button", { name: "Buyer lab", exact: true }).click();
  await expect(page.getByText("SIMULATED / NO REAL MONEY", { exact: false }).first()).toBeVisible();
  await page.getByLabel("Search catalog", { exact: true }).fill(offer.title);
  await page.getByRole("button", { name: "Filter Resources", exact: true }).click();
  const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: offer.title, exact: true }) });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Choose Resource", exact: true }).click();
}

async function requestQuote(page: Page): Promise<{ id: string }> {
  const response = page.waitForResponse((value) =>
    value.url().endsWith("/api/quotes") && value.request().method() === "POST",
  );
  await page.getByRole("button", { name: "Request quote", exact: true }).click();
  const created = await response;
  expect([200, 201]).toContain(created.status());
  return await created.json() as { id: string };
}

test("client budget refusal occurs before creating a quote or confirming payment", async ({ page }) => {
  let quoteRequests = 0;
  let confirmationRequests = 0;
  page.on("request", (request) => {
    if (request.method() !== "POST") return;
    if (new URL(request.url()).pathname === "/api/quotes") quoteRequests++;
    if (/\/api\/quotes\/[^/]+\/confirm$/.test(new URL(request.url()).pathname)) confirmationRequests++;
  });
  await chooseOffer(page);
  await page.getByRole("textbox", { name: /^Buyer budget \(USD\)/ }).fill("1.00");
  const quoteButton = page.getByRole("button", { name: "Request quote", exact: true });
  // The policy may disable the action immediately or refuse it with an alert.
  if (await quoteButton.isEnabled()) await quoteButton.click();
  await expect(page.getByRole("alert")).toContainText(/budget/i);
  expect(quoteRequests).toBe(0);
  expect(confirmationRequests).toBe(0);
});

test("unpaid delivery and other sessions are denied; paid bytes and receipt survive reload", async ({ page, browser }) => {
  await chooseOffer(page);
  await page.getByRole("textbox", { name: /^Buyer budget \(USD\)/ }).fill("5.00");
  const quote = await requestQuote(page);
  const unpaid = await page.request.get(`/api/quotes/${quote.id}/download`);
  expect(unpaid.status()).toBe(402);
  const other = await browser.newContext();
  try {
    await other.request.get(`${origin}/api/session`);
    expect((await other.request.get(`${origin}/api/quotes/${quote.id}`)).status()).toBe(404);
    expect((await other.request.get(`${origin}/api/quotes/${quote.id}/download`)).status()).toBe(404);
  } finally {
    await other.close();
  }
  await page.getByRole("button", { name: "Confirm simulated purchase", exact: true }).click();
  await expect(page.getByText(/SIM-[A-Za-z0-9-]+/).first()).toBeVisible();
  const firstReceipt = await page.request.get(`/api/quotes/${quote.id}`);
  const paid = await firstReceipt.json() as { receipt_id: string; transaction_hash: string | null; sha256: string };
  expect(paid.receipt_id).toMatch(/^SIM-/);
  expect(paid.transaction_hash).toBeNull();
  expect(paid.sha256).toBe(offer.sha256);
  const downloaded = await page.request.get(`/api/quotes/${quote.id}/download`);
  expect(downloaded.status()).toBe(200);
  const data = await downloaded.body();
  expect(data.equals(syntheticCSV)).toBeTruthy();
  expect(createHash("sha256").update(data).digest("hex")).toBe(offer.sha256);
  await page.reload();
  await page.getByRole("button", { name: "Buyer lab", exact: true }).click();
  await expect(page.getByText(paid.receipt_id, { exact: false }).first()).toBeVisible();
  await page.getByRole("button", { name: "Download and analyze CSV", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Route comparison", exact: true })).toBeVisible();
  await expect(page.getByText("Singapore-Jakarta", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("Singapore-Port Klang", { exact: true }).first()).toBeVisible();
  await expect(page.getByRole("link", { name: "Download verified CSV", exact: true })).toBeVisible();
});

test("a transient confirmation error retains the quote for an explicit retry", async ({ page }) => {
  await chooseOffer(page);
  await page.getByRole("textbox", { name: /^Buyer budget \(USD\)/ }).fill("5.00");
  const quote = await requestQuote(page);
  await page.route(`**/api/quotes/${quote.id}/confirm`, async (route) => {
    await route.fulfill({ status: 503, json: { detail: { code: "unavailable", message: "Payment verification temporarily unavailable. Retry the same quote." } } });
  }, { times: 1 });
  await page.getByRole("button", { name: "Confirm simulated purchase", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("temporarily unavailable");
  await expect(page.getByRole("button", { name: "Download and analyze CSV", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "Confirm simulated purchase", exact: true }).click();
  await expect(page.getByText(/SIM-[A-Za-z0-9-]+/).first()).toBeVisible();
  const confirmed = await page.request.get(`/api/quotes/${quote.id}`);
  expect((await confirmed.json() as { status: string }).status).toBe("paid");
});
