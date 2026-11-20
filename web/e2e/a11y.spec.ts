import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "./fixtures";
import { LOCKED, PASSWORD } from "./env";

const PATHS = ["/", "/activity", "/insights", "/tools", "/cache", "/sessions", "/settings"];

for (const scheme of ["light", "dark"] as const) {
  test.describe(`${scheme} theme`, () => {
    test.use({ colorScheme: scheme });

    for (const path of PATHS) {
      test(`${path} has no WCAG A/AA violations`, async ({ page }) => {
        await page.goto(path);
        await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
        await expect(page.getByText("Loading…")).toHaveCount(0);
        const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
        expect(violations.map((v) => `${v.id}: ${v.nodes.map((n) => n.target.join(" ")).slice(0, 3).join(" | ")}`))
          .toEqual([]);
      });
    }
  });
}

test("login page has no violations and a labelled field", async ({ page, consoleErrors }) => {
  await page.goto(LOCKED);
  await expect(page.getByLabel("Password")).toBeVisible();
  const { violations } = await new AxeBuilder({ page }).withTags(["wcag2a", "wcag2aa", "wcag21aa"]).analyze();
  expect(violations.map((v) => v.id)).toEqual([]);
  await page.getByLabel("Password").fill("wrong-password");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("alert")).toHaveText("Wrong password");
  consoleErrors.length = 0; // the browser logs the expected 401
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
});

test("skip link moves focus to the main region and routes set the page title", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", { name: "Skip to content" })).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("main")).toBeFocused();
  await page.getByRole("navigation", { name: "Main" }).getByRole("link", { name: "Cache" }).click();
  await expect(page).toHaveTitle("Cache · WhereAreMyTokens");
});

test("responds with security headers and no inline script is needed", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  const res = await page.goto("/");
  expect(res?.headers()["content-security-policy"]).toContain("script-src 'self'");
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
  expect(errors.filter((e) => /Content Security Policy/i.test(e))).toEqual([]);
});
