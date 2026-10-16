export function tokens(n: number): string {
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return String(n);
}

export type Currency = "EUR" | "USD";

const SYMBOLS: Record<Currency, string> = { EUR: "€", USD: "$" };
let display: { code: Currency; eurPerUsd: number } = { code: "USD", eurPerUsd: 1 };

/** Set once from /api/settings, before the dashboard renders (see SettingsGate in main.tsx). */
export function setCurrency(code: Currency, eurPerUsd: number) {
  display = { code, eurPerUsd };
}

export function currencySymbol(): string {
  return SYMBOLS[display.code];
}

/** USD (as every amount from the API) to the display currency. */
export function fromUsd(n: number): number {
  return display.code === "EUR" ? n * display.eurPerUsd : n;
}

/** Display currency back to USD, for amounts typed in by the user. */
export function toUsd(n: number): number {
  return display.code === "EUR" ? n / display.eurPerUsd : n;
}

/** Format an amount given in USD, in the display currency. */
export function money(usd: number): string {
  const n = fromUsd(usd);
  const sign = n < 0 ? "-" : "";
  const sym = SYMBOLS[display.code];
  const a = Math.abs(n);
  if (a >= 100) return `${sign}${sym}${a.toFixed(0)}`;
  if (a >= 1) return `${sign}${sym}${a.toFixed(2)}`;
  if (a === 0) return `${sym}0`;
  return `${sign}${sym}${a.toFixed(3)}`;
}

export function pct(n: number | null): string {
  return n === null ? "–" : `${(n * 100).toFixed(1)}%`;
}

export function dateTime(iso: string | null): string {
  if (!iso) return "–";
  return new Date(iso).toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function shortModel(model: string): string {
  return model.replace(/^claude-/, "").replace(/-\d{8}$/, "");
}

export function truncate(s: string | null, n: number): string {
  if (!s) return "";
  const one = s.replace(/\s+/g, " ").trim();
  return one.length > n ? `${one.slice(0, n - 1)}…` : one;
}

/** Every calendar day between the first and last active day, so idle days show as gaps. */
export function continuousDays(active: string[]): string[] {
  if (active.length === 0) return [];
  const sorted = [...active].sort();
  const out: string[] = [];
  const end = new Date(`${sorted[sorted.length - 1]}T00:00:00Z`);
  for (let d = new Date(`${sorted[0]}T00:00:00Z`); d <= end; d.setUTCDate(d.getUTCDate() + 1)) {
    out.push(d.toISOString().slice(0, 10));
  }
  return out;
}
