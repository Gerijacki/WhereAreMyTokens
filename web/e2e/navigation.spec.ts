import { expect, test } from "./fixtures";

const PAGES = [
  { link: "Overview", heading: "Overview" },
  { link: "Activity", heading: "Activity" },
  { link: "Insights", heading: "Insights" },
  { link: "Tools", heading: "Tools" },
  { link: "Cache", heading: "Cache" },
  { link: "Sessions", heading: "Sessions" },
];

test("every page loads from the navigation", async ({ page }) => {
  await page.goto("/");
  const nav = page.getByRole("navigation");
  for (const p of PAGES) {
    await nav.getByRole("link", { name: p.link, exact: true }).click();
    await expect(page.getByRole("heading", { level: 1, name: p.heading })).toBeVisible();
    await expect(page.getByText("Failed to load")).toHaveCount(0);
  }
});

test("range and project filters survive page changes", async ({ page }) => {
  await page.goto("/");
  await page.getByRole("group", { name: "Time range" }).getByRole("button", { name: "7d" }).click();
  await expect(page).toHaveURL(/days=7/);
  await page.getByRole("navigation").getByRole("link", { name: "Activity" }).click();
  await expect(page).toHaveURL(/\/activity\?.*days=7/);
  await expect(page.getByRole("group", { name: "Time range" }).getByRole("button", { name: "7d" }))
    .toHaveAttribute("aria-pressed", "true");
});

test("unknown paths fall back to the dashboard", async ({ page }) => {
  await page.goto("/no/such/page");
  await expect(page.getByRole("navigation")).toBeVisible();
});
