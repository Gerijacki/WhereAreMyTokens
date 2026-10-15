import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get, type CategoriesData, type InsightsData } from "../api";
import { CATEGORY_LABELS, categoryColor } from "../categories";
import { useFilters } from "../filters";
import { pct, usd } from "../format";
import { InsightCard } from "../pages/Insights";
import { Card, Empty } from "./ui";

export function CategoryBreakdown() {
  const { days, projectId } = useFilters();
  const q = useQuery({
    queryKey: ["categories", days, projectId],
    queryFn: () => get<CategoriesData>("/categories", { days, project_id: projectId }),
  });
  const rows = q.data?.by_category ?? [];
  const total = rows.reduce((a, c) => a + c.cost_usd, 0) || 1;
  const max = Math.max(...rows.map((r) => r.cost_usd), 0.0001);
  return (
    <Card title="Work categories" subtitle="Where the cost went, by kind of work"
      action={<Link to="/activity" className="text-xs secondary hover:underline">Activity →</Link>}>
      {rows.length === 0 ? <Empty>No categorized prompts yet.</Empty> : (
        <ul className="space-y-2.5">
          {rows.map((c) => (
            <li key={c.category}>
              <div className="flex justify-between text-sm gap-2">
                <span>{CATEGORY_LABELS[c.category] ?? c.category} <span className="muted text-xs">· {c.prompts} prompts</span></span>
                <span className="num whitespace-nowrap">{usd(c.cost_usd)} <span className="muted">· {pct(c.cost_usd / total)}</span></span>
              </div>
              <div className="h-2 rounded mt-1" style={{ background: "var(--surface-2)" }}>
                <div className="h-2 rounded" style={{ width: `${(c.cost_usd / max) * 100}%`, background: categoryColor(c.category) }} />
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function TopInsights() {
  const { projectId } = useFilters();
  const q = useQuery({
    queryKey: ["insights", "open", projectId],
    queryFn: () => get<InsightsData>("/insights", { status: "open", project_id: projectId }),
  });
  const items = (q.data?.items ?? []).filter((i) => i.est_usd_month > 0).slice(0, 3);
  return (
    <Card title="Biggest savings" subtitle={q.data ? `${usd(q.data.summary.open_usd_month)}/mo across ${q.data.summary.open} open insights` : undefined}
      action={<Link to="/insights" className="text-xs secondary hover:underline">All insights →</Link>}>
      {items.length === 0 ? <Empty>No savings found yet.</Empty> : (
        <div className="space-y-2">{items.map((i) => <InsightCard key={i.id} insight={i} compact />)}</div>
      )}
    </Card>
  );
}
