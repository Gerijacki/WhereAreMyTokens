import { expect, test } from "./fixtures";
import { LOCKED, PASSWORD } from "./env";

test.use({ baseURL: LOCKED });

test("the dashboard asks for the password", async ({ page, consoleErrors }) => {
  await page.goto("/");
  await expect(page.getByText("Enter the dashboard password.")).toBeVisible();

  await page.getByLabel("Password").fill("wrong");
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByText("Wrong password")).toBeVisible();
  consoleErrors.length = 0; // the browser logs the expected 401s

  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Overview" })).toBeVisible();
});

test("the API rejects requests without a session", async ({ request }) => {
  expect((await request.get("/api/overview")).status()).toBe(401);
  expect((await request.get("/api/health")).status()).toBe(200);
});
