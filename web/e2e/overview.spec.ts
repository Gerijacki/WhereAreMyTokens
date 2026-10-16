import { expect, test } from "./fixtures";

test("headline numbers and charts render", async ({ page }) => {
  await page.goto("/?days=0");
  const cost = page.locator(".card", { hasText: "API-equivalent cost" }).first();
  await expect(cost).toContainText(/\$\d/);
  await expect(page.getByRole("img", { name: /daily API-equivalent cost by model/ }).locator("svg")).toBeVisible();
});

test("plan value compares the last 30 days with the configured plan", async ({ page }) => {
  await page.goto("/");
  const card = page.locator(".card", { has: page.getByRole("heading", { name: "Plan value" }) });
  await expect(card.getByRole("combobox", { name: "Your plan" })).toHaveValue("max5x"); // WAMT_PLAN in server.mjs
  await expect(card).toContainText(/\d\.\d×/);
  await expect(card.getByRole("img").locator("svg")).toBeVisible();

  await card.getByRole("combobox", { name: "Your plan" }).selectOption("pro");
  await expect(card).toContainText("Pro");
  await page.reload();
  await expect(card.getByRole("combobox", { name: "Your plan" })).toHaveValue("pro"); // remembered in the browser
});

test("budgets can be added and removed", async ({ page }) => {
  await page.goto("/");
  const card = page.locator(".card", { has: page.getByRole("heading", { name: "Budgets" }) });
  await card.getByRole("button", { name: "Add budget" }).click();
  const form = card.getByRole("form", { name: "New budget" });
  await form.getByRole("combobox", { name: "Period" }).selectOption("week");
  await form.getByRole("spinbutton", { name: "Limit in USD" }).fill("0.5");
  await form.getByRole("button", { name: "Save" }).click();

  const budget = card.getByTestId("budget").filter({ hasText: "Weekly" });
  await expect(budget).toBeVisible();
  await expect(budget).toContainText("of $0.500");
  await budget.getByRole("button", { name: "Delete weekly budget" }).click();
  await expect(card.getByTestId("budget")).toHaveCount(0);
});
