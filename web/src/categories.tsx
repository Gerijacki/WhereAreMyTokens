import type { Theme } from "./components/Chart";

/**
 * Fixed colour slot per category (never by rank). The palette validates 8 slots, so the
 * first seven categories get their own hue and the rest share slot 8 as "Other" in charts.
 * Tables still show the real category name.
 */
const SLOTS: Record<string, number> = {
  coding: 0,
  debugging: 1,
  exploration: 2,
  testing: 3,
  ops: 4,
  planning: 5,
  research: 6,
};
export const OTHER_SLOT = 7;

export const CATEGORY_LABELS: Record<string, string> = {
  coding: "Coding",
  debugging: "Debugging",
  exploration: "Exploration",
  testing: "Testing",
  ops: "Ops & git",
  planning: "Planning",
  research: "Research",
  review: "Review",
  docs: "Docs",
  chat: "Chat",
  uncategorized: "Uncategorized",
};

export function chartGroup(category: string): string {
  return category in SLOTS ? category : "other";
}

export function groupLabel(group: string): string {
  return group === "other" ? "Other" : (CATEGORY_LABELS[group] ?? group);
}

export const CHART_GROUPS = [...Object.keys(SLOTS), "other"];

export function categoryColor(category: string, theme?: Theme): string {
  const slot = SLOTS[category] ?? OTHER_SLOT;
  return theme ? theme.series[slot] : `var(--series-${slot + 1})`;
}

export function CategoryChip({ category }: { category: string | null }) {
  const c = category ?? "uncategorized";
  return (
    <span className="chip">
      <span aria-hidden style={{ width: 8, height: 8, borderRadius: 2, background: categoryColor(c) }} />
      {CATEGORY_LABELS[c] ?? c}
    </span>
  );
}
