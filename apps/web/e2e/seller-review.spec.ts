import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";

function password(name: string): string {
  const value = process.env[name];
  if (!value)
    throw new Error(
      `Set ${name} to the same demo password used by the API seed command.`,
    );
  return value;
}

async function signIn(page: Page, email: string, secret: string) {
  await page.getByRole("button", { name: "Sign in", exact: true }).click();
  await page.getByLabel("Email", { exact: true }).fill(email);
  await page.getByLabel("Password", { exact: true }).fill(secret);
  await page
    .locator("form")
    .getByRole("button", { name: "Sign in", exact: true })
    .click();
  await expect(
    page.getByRole("button", { name: "Sign out", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("heading", {
      name:
        email === "reviewer@sliver.local"
          ? "Review the source."
          : "Prepare. Review. Publish.",
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByRole("alert")).toHaveCount(0);
}

async function signOut(page: Page) {
  await page.getByRole("button", { name: "Sign out", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Data, with a source." }),
  ).toBeVisible();
}

test("private upload, cross-seller isolation, review, and metadata-only publication", async ({
  page,
}) => {
  const sellerPassword = password("SLIVER_SELLER_A_PASSWORD");
  const otherSellerPassword = password("SLIVER_SELLER_B_PASSWORD");
  const reviewerPassword = password("SLIVER_REVIEWER_PASSWORD");
  const suffix = `${Date.now()}-${test.info().retry}`;
  const title = `Harbor observations ${suffix}`;
  const privateValue = `PRIVATE-OBSERVATION-${suffix}`;
  const declaration = `Synthetic private rights declaration ${suffix}. Approved for this local demonstration.`;

  await page.goto("/");
  await signIn(page, "seller-a@sliver.local", sellerPassword);
  await expect(
    page.getByRole("heading", { name: "Prepare. Review. Publish." }),
  ).toBeVisible();

  const upload = page.getByRole("form", { name: "Upload a dataset" });
  await upload.getByLabel("Dataset title", { exact: true }).fill(title);
  await upload.getByLabel("CSV file", { exact: true }).setInputFiles({
    name: "harbor-observations.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`station,waiting_hours\n${privateValue},3.7\n`),
  });
  await upload
    .getByLabel("Source", { exact: true })
    .fill("Synthetic Singapore port observations");
  await upload
    .getByLabel("Collection date", { exact: true })
    .fill("2026-11-02");
  await upload
    .getByLabel("Collection method", { exact: true })
    .fill("Synthetic fixture generated for local demonstration");
  await upload
    .getByLabel("Coverage", { exact: true })
    .fill("Singapore, one synthetic observation");
  await upload
    .getByLabel("Rights declaration", { exact: true })
    .fill(declaration);
  await upload.getByLabel("CSV file", { exact: true }).setInputFiles({
    name: "invalid-observations.csv",
    mimeType: "text/csv",
    buffer: Buffer.from("station,waiting_hours\nmissing-a-column\n"),
  });
  await upload.getByRole("button", { name: "Upload and validate" }).click();
  await expect(upload.getByRole("alert")).toBeVisible();
  await expect(page.getByLabel("Select dataset", { exact: true })).toHaveCount(
    0,
  );
  await upload.getByLabel("CSV file", { exact: true }).setInputFiles({
    name: "harbor-observations.csv",
    mimeType: "text/csv",
    buffer: Buffer.from(`station,waiting_hours\n${privateValue},3.7\n`),
  });
  await upload.getByRole("button", { name: "Upload and validate" }).click();
  await expect(
    page.getByText("Dataset uploaded. File checks passed;", { exact: false }),
  ).toBeVisible();
  await page.getByRole("button", { name: "View private preview" }).click();
  await expect(
    page.getByRole("cell", { name: privateValue, exact: true }),
  ).toBeVisible();

  const datasetId = await page
    .getByLabel("Select dataset", { exact: true })
    .inputValue();
  expect(datasetId).toBeTruthy();
  const resourceForm = page.getByRole("form", { name: "Create Resource" });
  await resourceForm.getByLabel("Resource title", { exact: true }).fill(title);
  await resourceForm
    .getByLabel("Public description", { exact: true })
    .fill(
      "A synthetic port-observation dataset for evaluating the publication workflow.",
    );
  await resourceForm.getByLabel("Price (USD)", { exact: true }).fill("12.50");
  await resourceForm
    .getByRole("button", { name: "Create draft Resource" })
    .click();
  const ownedResource = page.getByRole("article", {
    name: `Resource ${title}`,
    exact: true,
  });
  await expect(ownedResource.getByText("Draft", { exact: true })).toBeVisible();
  await ownedResource
    .getByRole("button", { name: "Submit for review" })
    .click();
  await expect(
    ownedResource.getByText("Awaiting review", { exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("seller-workspace.png"),
    fullPage: true,
  });
  await signOut(page);
  await expect(
    page.getByRole("heading", { name: title, exact: true }),
  ).toHaveCount(0);

  await signIn(page, "seller-b@sliver.local", otherSellerPassword);
  await expect(
    page.getByRole("option", { name: title, exact: true }),
  ).toHaveCount(0);
  const deniedPreview = await page.request.get(
    `/api/datasets/${datasetId}/preview`,
  );
  expect(deniedPreview.status()).toBe(404);
  await signOut(page);

  await signIn(page, "reviewer@sliver.local", reviewerPassword);
  const submission = page.getByRole("article", {
    name: `Review ${title}`,
    exact: true,
  });
  await submission.getByRole("button", { name: "Inspect submission" }).click();
  await submission
    .getByText("Private rights declaration", { exact: true })
    .click();
  await expect(
    submission.getByText(declaration, { exact: true }),
  ).toBeVisible();
  await submission
    .getByRole("button", { name: "View private preview" })
    .click();
  await expect(
    submission.getByRole("cell", { name: privateValue, exact: true }),
  ).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath("reviewer-inspection.png"),
    fullPage: true,
  });
  await submission
    .getByLabel("Decision", { exact: true })
    .selectOption("approve");
  await submission
    .getByLabel("Review reason", { exact: true })
    .fill(
      "Synthetic source and declared demo rights reviewed for publication.",
    );
  await submission
    .getByRole("button", { name: "Record review", exact: true })
    .click();
  await expect(
    page.getByText("Review recorded.", { exact: false }),
  ).toBeVisible();
  await signOut(page);

  const published = page.getByRole("article", {
    name: `Published Resource ${title}`,
    exact: true,
  });
  await expect(published).toBeVisible();
  await expect(published.getByText("$12.50", { exact: true })).toBeVisible();
  await published.getByText("Schema and provenance", { exact: true }).click();
  await expect(
    published.getByText("Synthetic Singapore port observations", {
      exact: true,
    }),
  ).toBeVisible();
  await expect(page.getByText(declaration, { exact: true })).toHaveCount(0);
  await expect(page.getByText(privateValue, { exact: true })).toHaveCount(0);
  const catalogResponse = await page.request.get("/api/catalog");
  expect(catalogResponse.ok()).toBeTruthy();
  const catalogText = await catalogResponse.text();
  expect(catalogText).not.toContain(privateValue);
  expect(catalogText).not.toContain(declaration);
  expect(catalogText).not.toContain("rights_statement");
  expect(catalogText).not.toContain("object_key");
  await page.screenshot({
    path: test.info().outputPath("published-catalog.png"),
    fullPage: true,
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(published).toBeVisible();
  const widths = await page.evaluate(() => ({
    content: document.documentElement.scrollWidth,
    viewport: window.innerWidth,
  }));
  expect(widths.content).toBeLessThanOrEqual(widths.viewport);
  await page.screenshot({
    path: test.info().outputPath("published-catalog-mobile.png"),
    fullPage: true,
  });
});
