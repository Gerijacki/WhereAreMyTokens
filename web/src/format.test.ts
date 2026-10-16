import { afterEach, describe, expect, it } from "vitest";
import { continuousDays, money, pct, setCurrency, shortModel, tokens, toUsd, truncate } from "./format";

describe("format", () => {
  it("abbreviates token counts", () => {
    expect([tokens(999), tokens(1_500), tokens(2_340_000), tokens(3_210_000_000)]).toEqual(["999", "1.5k", "2.3M", "3.21B"]);
  });

  afterEach(() => setCurrency("USD", 1));

  it("shows more decimals for small amounts", () => {
    expect([money(0), money(0.0123), money(4.5), money(1234.4)]).toEqual(["$0", "$0.012", "$4.50", "$1234"]);
  });

  it("converts USD amounts to euros for display, and typed euros back", () => {
    setCurrency("EUR", 0.9);
    expect([money(10), money(200), money(-1)]).toEqual(["€9.00", "€180", "-€0.900"]);
    expect(toUsd(9)).toBeCloseTo(10);
  });

  it("formats ratios and missing values", () => {
    expect(pct(0.973)).toBe("97.3%");
    expect(pct(null)).toBe("–");
  });

  it("shortens model ids", () => {
    expect(shortModel("claude-opus-5-5")).toBe("opus-5-5");
    expect(shortModel("claude-sonnet-4-20250514")).toBe("sonnet-4");
  });

  it("truncates on one line", () => {
    expect(truncate("a\n  b   c", 10)).toBe("a b c");
    expect(truncate("abcdefghij", 5)).toBe("abcd…");
    expect(truncate(null, 5)).toBe("");
  });

  it("fills idle days between active ones", () => {
    expect(continuousDays(["2026-10-03", "2026-09-30"])).toEqual(["2026-09-30", "2026-10-01", "2026-10-02", "2026-10-03"]);
    expect(continuousDays([])).toEqual([]);
  });
});
