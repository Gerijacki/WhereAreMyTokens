import { expect, test } from "./fixtures";

test("a session opens with its prompts and cost", async ({ page }) => {
  await page.goto("/sessions?days=0");
  const first = page.locator("table.data-table tbody tr").first().getByRole("link").first();
  const title = (await first.textContent())!.trim();
  await first.click();
  await expect(page).toHaveURL(/\/sessions\/[\w-]+/);
  await expect(page.getByRole("heading", { level: 1 })).toHaveText(title);
  await expect(page.locator("[id^=turn-]").first()).toBeVisible();
});
