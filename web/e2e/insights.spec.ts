import { expect, test } from "./fixtures";

test("insights list fixes with evidence", async ({ page }) => {
  await page.goto("/insights");
  const cards = page.locator(".card", { has: page.getByRole("heading", { level: 3 }) });
  await expect(cards.first()).toBeVisible();
  expect(await cards.count()).toBeGreaterThanOrEqual(5);

  // Pin the card by its title: the button's label changes once the fix is shown.
  const title = await cards.filter({ has: page.getByRole("button", { name: /^Show fix/ }) }).first()
    .getByRole("heading", { level: 3 }).textContent();
  const withFix = cards.filter({ has: page.getByRole("heading", { level: 3, name: title!, exact: true }) });
  await withFix.getByRole("button", { name: /^Show fix/ }).click();
  await expect(withFix.locator("pre.code")).not.toBeEmpty();
  await expect(withFix.getByText("Seen in")).toBeVisible();
});

test("marking an insight done measures it, reopening restores it", async ({ page }) => {
  await page.goto("/insights");
  const first = page.locator(".card", { has: page.getByRole("heading", { level: 3 }) }).first();
  const title = (await first.getByRole("heading", { level: 3 }).textContent())!;
  await first.getByRole("button", { name: "Mark done" }).click();
  await expect(page.getByRole("heading", { level: 3, name: title, exact: true })).toHaveCount(0);

  await page.getByRole("group", { name: "Status" }).getByRole("button", { name: /^Done/ }).click();
  const done = page.locator(".card", { has: page.getByRole("heading", { level: 3, name: title, exact: true }) });
  await expect(done).toContainText("Measuring…"); // needs a week of data after being marked done
  await expect(page.locator(".card", { hasText: "Realized savings" }).first()).toContainText("1 measuring");

  await done.getByRole("button", { name: "Reopen" }).click();
  await page.getByRole("group", { name: "Status" }).getByRole("button", { name: /^Open/ }).click();
  await expect(page.getByRole("heading", { level: 3, name: title, exact: true })).toBeVisible();
});
