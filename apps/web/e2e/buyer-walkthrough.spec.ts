import { test, expect } from "@playwright/test";
import { approvedOffer } from "./buyer-fixture";

// A separate file lets Playwright always retain this recording, including success.
test.use({ video: { mode: "on", size: { width: 1440, height: 1000 } }, viewport: { width: 1440, height: 1000 } });

test("walkthrough: discover, budget, quote, simulated receipt, verified answer", async ({ page, playwright }) => {
  const offer = await approvedOffer(playwright, `Synthetic walkthrough routes ${Date.now()}`);
  await page.goto("/");
  await page.getByRole("button", { name: "Buyer lab", exact: true }).click();
  await expect(page.getByText("SIMULATED / NO REAL MONEY", { exact: false }).first()).toBeVisible();
  await page.getByLabel("Search catalog", { exact: true }).fill(offer.title);
  await page.getByRole("button", { name: "Filter Resources", exact: true }).click();
  const card = page.getByRole("article").filter({ has: page.getByRole("heading", { name: offer.title, exact: true }) });
  await expect(card).toBeVisible();
  await card.getByRole("button", { name: "Choose Resource", exact: true }).click();
  await page.getByRole("textbox", { name: /^Buyer budget \(USD\)/ }).fill("1.00");
  const quoteButton = page.getByRole("button", { name: "Request quote", exact: true });
  if (await quoteButton.isEnabled()) await quoteButton.click();
  await expect(page.getByRole("alert")).toContainText(/budget/i);
  await page.screenshot({ path: test.info().outputPath("01-budget-refusal.png"), fullPage: true });
  await page.getByRole("textbox", { name: /^Buyer budget \(USD\)/ }).fill("5.00");
  const created = page.waitForResponse((value) => value.url().endsWith("/api/quotes") && value.request().method() === "POST");
  await quoteButton.click();
  const response = await created;
  expect([200, 201]).toContain(response.status());
  const quote = await response.json() as { id: string };
  await expect(page.getByRole("button", { name: "Confirm simulated purchase", exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("02-immutable-quote.png"), fullPage: true });
  await page.getByRole("button", { name: "Confirm simulated purchase", exact: true }).click();
  await expect(page.getByText(/SIM-[A-Za-z0-9-]+/).first()).toBeVisible();
  await page.getByRole("button", { name: "Download and analyze CSV", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Route comparison", exact: true })).toBeVisible();
  const comparison = page.getByRole("region", { name: "Route comparison", exact: true });
  await expect(comparison.getByRole("row", { name: "Singapore-Jakarta 4 15.0 50.0%", exact: true })).toBeVisible();
  await expect(comparison.getByRole("row", { name: "Singapore-Port Klang 4 10.0 75.0%", exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath("03-receipt-and-route-answer.png"), fullPage: true });
  const receiptResponse = await page.request.get(`/api/quotes/${quote.id}`);
  const receipt = await receiptResponse.json() as { id: string; receipt_id: string; sha256: string; size_bytes: number; mode: string; transaction_hash: string | null };
  expect(receipt.mode).toBe("simulated");
  expect(receipt.transaction_hash).toBeNull();
  expect(receipt.sha256).toBe(offer.sha256);
  expect(receipt.size_bytes).toBe(offer.sizeBytes);
  await test.info().attach("simulated-purchase-evidence", {
    body: JSON.stringify({ ...receipt, fixture: "examples/fixtures/synthetic-routes.csv", expected_analysis: {
      "Singapore-Jakarta": { average_delay_minutes: 15, on_time_percent: 50 },
      "Singapore-Port Klang": { average_delay_minutes: 10, on_time_percent: 75 },
    } }, null, 2),
    contentType: "application/json",
  });
});
