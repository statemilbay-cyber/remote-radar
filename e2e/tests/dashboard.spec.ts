import { expect, test, type Page } from "@playwright/test";

// Sample data (src/remote_radar/demo.py): 8 roles, 4 eligible, 4 excluded for different reasons.
const ELIGIBLE = 4;
const TOTAL = 8;

const jobRows = (page: Page) => page.locator("tr.job");

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  page.on("pageerror", (err) => errors.push(err.message));
  await page.goto("/");
  await expect(jobRows(page).first()).toBeVisible();
  expect(errors, "no uncaught errors on load").toEqual([]);
});

test("shows only eligible roles by default, best first", async ({ page }) => {
  await expect(page.locator("#count")).toHaveText(`${ELIGIBLE} shown`);
  await expect(jobRows(page)).toHaveCount(ELIGIBLE);

  const scores = await page.locator("tr.job .score").allInnerTexts();
  const numbers = scores.map(Number);
  expect(numbers).toEqual([...numbers].sort((a, b) => b - a));
});

test("summary tiles match the data", async ({ page }) => {
  const kpis = page.getByRole("region", { name: "Summary" });
  await expect(kpis).toContainText(`${ELIGIBLE}roles match the profile`);
  await expect(kpis).toContainText(`${TOTAL}roles scanned`);
});

test("search narrows the list by title, company or stack", async ({ page }) => {
  const search = page.getByRole("searchbox", { name: "Search" });

  await search.fill("n8n");
  await expect(jobRows(page)).toHaveCount(1);
  await expect(jobRows(page).first()).toContainText("Workflow Automation Engineer");

  await search.fill("globex");
  await expect(jobRows(page)).toHaveCount(1);
  await expect(jobRows(page).first()).toContainText("Python Data Engineer");

  await search.fill("no such role");
  await expect(page.locator("#count")).toHaveText("0 shown");
});

test("track and engagement filters combine", async ({ page }) => {
  await page.getByRole("combobox", { name: "Track" }).selectOption({ label: "QA" });
  await expect(jobRows(page)).toHaveCount(1);

  await page.getByRole("combobox", { name: "Track" }).selectOption({ label: "All tracks" });
  await page.getByRole("combobox", { name: "Engagement" }).selectOption({ label: "Contract / B2B" });
  await expect(jobRows(page)).toHaveCount(2);
});

test("excluded roles stay visible on demand, with the reason", async ({ page }) => {
  await page.getByLabel("Show excluded").check();
  await expect(jobRows(page)).toHaveCount(TOTAL);

  await jobRows(page).filter({ hasText: "Backend Engineer (Python)" }).click();
  await expect(page.locator("tr.details:not([hidden])")).toContainText("Restricted to US");
});

test("minimum score slider hides weaker matches", async ({ page }) => {
  const before = await jobRows(page).count();
  await page.locator("#min").fill("90");
  await expect(page.locator("#minv")).toHaveText("90");
  const after = await jobRows(page).count();
  expect(after).toBeLessThan(before);
  for (const text of await page.locator("tr.job .score").allInnerTexts()) {
    expect(Number(text)).toBeGreaterThanOrEqual(90);
  }
});

test("rows expand with the keyboard", async ({ page }) => {
  const first = jobRows(page).first();
  await first.focus();
  await page.keyboard.press("Enter");
  const details = page.locator("tr.details").first();
  await expect(details).toBeVisible();
  await expect(details).toContainText("Pay from");
  await page.keyboard.press("Enter");
  await expect(details).toBeHidden();
});

test("listing links open the original posting in a new tab, safely", async ({ page }) => {
  const link = jobRows(page).first().getByRole("link");
  await expect(link).toHaveAttribute("href", /^https:\/\/example\.com\/jobs\//);
  await expect(link).toHaveAttribute("target", "_blank");
  await expect(link).toHaveAttribute("rel", /noopener/);
});

test("page never scrolls horizontally", async ({ page }) => {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
