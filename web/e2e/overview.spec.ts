import { expect, test } from "./fixtures";

test("headline numbers and charts render", async ({ page }) => {
  await page.goto("/?days=0");
  const cost = page.locator(".card", { hasText: "API-equivalent cost" }).first();
  await expect(cost).toContainText(/€\d/); // EUR is the default display currency
  await expect(page.getByRole("img", { name: /daily API-equivalent cost by model/ }).locator("svg")).toBeVisible();
});

test("plan value compares the last 30 days with the chosen plan", async ({ page }) => {
  await page.goto("/");
  const card = page.locator(".card", { has: page.getByRole("heading", { name: "Plan value" }) });
  const select = card.getByRole("combobox", { name: "Your plan" });
  await expect(select).toHaveValue("pro"); // no plan chosen yet: the cheapest
  await expect(card).toContainText(/\d\.\d×/);
  await expect(card.getByRole("img").locator("svg")).toBeVisible();

  try {
    await select.selectOption("max5x");
    await expect(card).toContainText("less than Max 5x");
    await page.reload();
    await expect(select).toHaveValue("max5x"); // saved on the server
    await expect(select.locator("option:checked")).toHaveText("Max 5x · €90/mo");
  } finally {
    await page.request.patch("/api/settings", { data: { plan: null } });
  }
});

test("budgets can be added and removed", async ({ page }) => {
  await page.goto("/");
  const card = page.locator(".card", { has: page.getByRole("heading", { name: "Budgets" }) });
  await card.getByRole("button", { name: "Add budget" }).click();
  const form = card.getByRole("form", { name: "New budget" });
  await form.getByRole("combobox", { name: "Period" }).selectOption("week");
  await form.getByRole("spinbutton", { name: "Limit" }).fill("0.5"); // typed in euros, stored in USD
  await form.getByRole("button", { name: "Save" }).click();

  const budget = card.getByTestId("budget").filter({ hasText: "Weekly" });
  await expect(budget).toBeVisible();
  await expect(budget).toContainText("of €0.500");
  await budget.getByRole("button", { name: "Delete weekly budget" }).click();
  await expect(card.getByTestId("budget")).toHaveCount(0);
});
