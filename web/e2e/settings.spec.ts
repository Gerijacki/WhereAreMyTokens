import { expect, test } from "./fixtures";

test("the theme can be switched from the header and from Settings", async ({ page }) => {
  await page.goto("/settings");
  const html = page.locator("html");
  await expect(html).not.toHaveAttribute("data-theme", /.*/);
  await page.getByRole("button", { name: /^System theme/ }).click();
  await expect(html).toHaveAttribute("data-theme", "light");
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "Dark" }).click();
  await expect(html).toHaveAttribute("data-theme", "dark");
  await expect(page.getByRole("button", { name: /^Dark theme/ })).toBeVisible(); // header follows
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "dark"); // applied before the app renders
  await page.getByRole("group", { name: "Theme" }).getByRole("button", { name: "System" }).click();
  await expect(html).not.toHaveAttribute("data-theme", /.*/);
});

test("amounts follow the display currency", async ({ page }) => {
  await page.goto("/settings");
  try {
    await page.getByRole("group", { name: "Currency" }).getByRole("button", { name: "USD" }).click();
    await page.waitForLoadState("load"); // switching currency reloads the page
    await expect(page.getByRole("group", { name: "Currency" }).getByRole("button", { name: "USD" }))
      .toHaveAttribute("aria-pressed", "true");
    await page.goto("/");
    await expect(page.locator(".card", { hasText: "API-equivalent cost" }).first()).toContainText(/\$\d/);
  } finally {
    await page.request.patch("/api/settings", { data: { currency: "EUR" } });
  }
  await page.goto("/");
  await expect(page.locator(".card", { hasText: "API-equivalent cost" }).first()).toContainText(/€\d/);
});

test("a dashboard password can be set, used and removed from Settings", async ({ page, consoleErrors }) => {
  const password = "e2e-ui-password";
  await page.goto("/settings");
  const security = page.locator(".card", { has: page.getByRole("heading", { name: "Security" }) });
  try {
    await security.getByLabel("Password", { exact: true }).fill(password);
    await security.getByRole("button", { name: "Set password" }).click();
    await expect(security.getByRole("status")).toContainText("Password saved");

    await page.getByRole("button", { name: "Log out" }).click();
    await expect(page.getByText("Enter the dashboard password.")).toBeVisible();
    consoleErrors.length = 0; // the browser logs the expected 401s
    await page.getByLabel("Password").fill(password);
    await page.getByRole("button", { name: "Sign in" }).click();
    await expect(page.getByRole("heading", { level: 1, name: "Settings" })).toBeVisible();

    await security.getByLabel("Current password").fill(password);
    await security.getByRole("button", { name: "Remove password" }).click();
    await expect(security.getByRole("status")).toContainText("Password removed");
    await expect(page.getByRole("button", { name: "Log out" })).toHaveCount(0);
  } finally {
    // Leave the shared server open for the other specs, whatever happened above.
    await page.request.post("/api/auth/login", { data: { password } });
    await page.request.delete("/api/auth/password", { data: { current: password } });
  }
});

test("devices can be added and revoked", async ({ page }) => {
  await page.goto("/settings");
  const devices = page.locator(".card", { has: page.getByRole("heading", { name: "Devices" }) });
  await devices.getByLabel("Device name").fill("e2e-laptop");
  await devices.getByRole("button", { name: "Add device" }).click();
  await expect(devices.getByTestId("device-token")).toContainText(/--token wamt_[\w-]{20,}/);
  const row = devices.getByRole("row", { name: /e2e-laptop/ });
  await expect(row).toContainText("active");
  await row.getByRole("button", { name: "Revoke e2e-laptop" }).click();
  await expect(row).toContainText("revoked");
});

test("data can be exported", async ({ page }) => {
  await page.goto("/settings");
  const exportCard = page.locator(".card", { has: page.getByRole("heading", { name: "Export" }) });
  await exportCard.getByRole("combobox", { name: "Export data" }).selectOption("daily");
  await exportCard.getByRole("combobox", { name: "Export range" }).selectOption("0");
  const [download] = await Promise.all([
    page.waitForEvent("download"),
    exportCard.getByRole("link", { name: "Download" }).click(),
  ]);
  expect(download.suggestedFilename()).toBe("wamt-daily-all.csv");
  const csv = await (await download.createReadStream()).toArray();
  const [header, ...rows] = Buffer.concat(csv).toString("utf-8").trim().split(/\r?\n/);
  expect(header).toBe("day,project,model,input_tokens,output_tokens,cache_write_5m,cache_write_1h,cache_read,"
    + "total_tokens,api_calls,cost_usd,cost_eur");
  expect(rows.length).toBeGreaterThan(10);
});
