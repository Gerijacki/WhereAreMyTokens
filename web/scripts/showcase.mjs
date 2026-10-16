// Regenerates the README screenshots (light and dark) and the demo GIF from synthetic demo data.
//
//   pnpm build && node scripts/showcase.mjs        (or `make screenshots` from the repo root)
//
// Needs backend/.venv (or WAMT_BIN), Playwright's Chromium and ffmpeg for the GIF.
import { spawn, spawnSync } from "node:child_process";
import { mkdirSync, rmSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "@playwright/test";

const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const out = join(web, "..", "docs", "screenshots");
const gif = join(web, "..", "docs", "demo.gif");
const port = 8792;
const base = `http://127.0.0.1:${port}`;

// Each page, the height to capture, and what to do before the shot.
const SHOTS = [
  { name: "overview", path: "/", height: 1520 },
  { name: "activity", path: "/activity", height: 1460 },
  { name: "insights", path: "/insights", height: 1180, prepare: openFirstFix },
  { name: "tools", path: "/tools", height: 1250 },
  { name: "cache", path: "/cache", height: 1100 },
  { name: "session", path: null, height: 1300 },
  { name: "settings", path: "/settings", height: 1250 },
];

async function openFirstFix(page) {
  await page.getByRole("button", { name: /^Show fix/ }).first().click();
}

async function api(method, path, body) {
  const res = await fetch(`${base}/api${path}`, {
    method, headers: { "Content-Type": "application/json" }, body: body && JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${method} ${path}: ${res.status} ${await res.text()}`);
  return res.json();
}

async function settle(page) {
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(700); // chart animations
}

async function screenshots(browser, sessionPath) {
  mkdirSync(out, { recursive: true });
  for (const scheme of ["light", "dark"]) {
    const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, colorScheme: scheme });
    for (const shot of SHOTS) {
      await page.goto(base + (shot.path ?? sessionPath));
      await settle(page);
      if (shot.prepare) {
        await shot.prepare(page);
        await settle(page);
      }
      await page.setViewportSize({ width: 1440, height: shot.height });
      await settle(page);
      await page.screenshot({ path: join(out, `${shot.name}-${scheme}.png`) });
      console.log(`  ${shot.name}-${scheme}.png`);
    }
    await page.close();
  }
}

async function recordGif(browser, sessionPath) {
  const videos = join(web, "e2e", ".data", "video");
  rmSync(videos, { recursive: true, force: true });
  const context = await browser.newContext({
    viewport: { width: 1280, height: 800 }, colorScheme: "light", recordVideo: { dir: videos, size: { width: 1280, height: 800 } },
  });
  const page = await context.newPage();
  const pause = (ms) => page.waitForTimeout(ms);
  await page.goto(base + "/");
  await settle(page);
  await pause(1600);
  await page.mouse.wheel(0, 380);
  await pause(1800);
  await page.getByRole("navigation").getByRole("link", { name: "Insights" }).click();
  await settle(page);
  await pause(1200);
  await page.getByRole("button", { name: /^Show fix/ }).first().click();
  await pause(2200);
  await page.getByRole("navigation").getByRole("link", { name: "Sessions" }).click();
  await settle(page);
  await pause(900);
  await page.goto(base + sessionPath);
  await settle(page);
  await pause(1800);
  await page.getByRole("button", { name: /^System theme/ }).click();
  await page.getByRole("button", { name: /^Light theme/ }).click(); // now dark
  await page.getByRole("navigation").getByRole("link", { name: "Overview" }).click();
  await settle(page);
  await pause(2200);
  const video = page.video();
  await context.close();
  const webm = await video.path();

  const filters = "fps=12,scale=960:-1:flags=lanczos";
  const palette = join(videos, "palette.png");
  for (const args of [
    ["-y", "-i", webm, "-vf", `${filters},palettegen=stats_mode=diff`, palette],
    ["-y", "-i", webm, "-i", palette, "-lavfi", `${filters}[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle`, gif],
  ]) {
    const r = spawnSync("ffmpeg", ["-loglevel", "error", ...args], { stdio: "inherit" });
    if (r.status !== 0) throw new Error("ffmpeg failed (is it installed?)");
  }
  console.log(`  demo.gif (${(statSync(gif).size / 1e6).toFixed(1)} MB)`);
}

const server = spawn(process.execPath, [join(web, "e2e", "server.mjs"), "--port", String(port), "--live"], { stdio: "inherit" });
try {
  for (let i = 0; ; i++) {
    try {
      if ((await fetch(`${base}/api/health`)).ok) break;
    } catch {
      // not up yet
    }
    if (i > 180) throw new Error("server did not start");
    await new Promise((r) => setTimeout(r, 1000));
  }
  // A realistic setup: a plan and two budgets, amounts in dollars for an international README.
  await api("PATCH", "/settings", { currency: "USD", plan: "pro" });
  await api("POST", "/budgets", { period: "month", limit_usd: 60 });
  await api("POST", "/budgets", { period: "week", limit_usd: 25 });
  const [top] = await api("GET", "/sessions?days=0&sort=cost&limit=1");
  const sessionPath = `/sessions/${top.id}`;

  const browser = await chromium.launch();
  console.log("Screenshots:");
  await screenshots(browser, sessionPath);
  if (!process.argv.includes("--no-gif")) {
    console.log("GIF:");
    await recordGif(browser, sessionPath);
  }
  await browser.close();
} finally {
  server.kill();
}
