// Starts a WAMT server for the end-to-end tests: fresh synthetic demo data (fixed seed), ingested and
// analyzed up front, then served with the collector off so nothing changes while tests run.
//
//   node e2e/server.mjs --port 8790 [--password secret]
//
// Uses the backend virtualenv (backend/.venv) unless WAMT_BIN points to a `wamt` executable.
// Serves the built dashboard from web/dist, so run `pnpm build` first (playwright.config.ts does).
import { spawn, spawnSync } from "node:child_process";
import { existsSync, mkdirSync, rmSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { parseArgs } from "node:util";

const { values } = parseArgs({ options: { port: { type: "string", default: "8790" }, password: { type: "string" } } });
const web = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const venv = join(web, "..", "backend", ".venv");
const wamt = process.env.WAMT_BIN
  ?? [join(venv, "bin", "wamt"), join(venv, "Scripts", "wamt.exe")].find((p) => existsSync(p))
  ?? "wamt";

const data = join(web, "e2e", ".data", values.port);
rmSync(data, { recursive: true, force: true });
mkdirSync(data, { recursive: true });
const env = {
  ...process.env,
  WAMT_CLAUDE_DATA_DIR: join(data, "demo"),
  WAMT_DATABASE_URL: `sqlite:///${join(data, "wamt.db")}`,
  WAMT_STATIC_DIR: join(web, "dist"),
  WAMT_INGEST_ENABLED: "false",
  WAMT_PLAN: "max5x",
  WAMT_TIMEZONE: "UTC",
  ...(values.password ? { WAMT_AUTH_PASSWORD: values.password, WAMT_SECRET_KEY: "e2e-only" } : {}),
};

for (const args of [["demo", "--dir", env.WAMT_CLAUDE_DATA_DIR, "--seed", "7"], ["ingest"], ["insights"]]) {
  const r = spawnSync(wamt, args, { env, stdio: ["ignore", "ignore", "inherit"] });
  if (r.status !== 0) {
    console.error(`\`wamt ${args[0]}\` failed (${r.error?.message ?? `exit ${r.status}`}). Is backend/.venv set up?`);
    process.exit(1);
  }
}

const server = spawn(wamt, ["serve", "--host", "127.0.0.1", "--port", values.port], { env, stdio: "inherit" });
for (const signal of ["SIGINT", "SIGTERM"]) process.on(signal, () => server.kill(signal));
server.on("exit", (code) => process.exit(code ?? 0));
