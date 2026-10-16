import { useCallback, useState, type FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, send, type BudgetPeriod, type BudgetRow, type PlanData, type ProjectRow } from "../api";
import { currencySymbol, money, pct, toUsd } from "../format";
import { Chart, axisStyle, baseOption, type Theme } from "./Chart";
import { Card, Empty } from "./ui";

/** A plan's price as listed in pricing.yaml (in its own currency, not converted back and forth). */
function planPrice(p: PlanData["plans"][number]): string {
  return `${p.price_currency === "EUR" ? "€" : "$"}${Number.isInteger(p.price) ? p.price : p.price.toFixed(2)}`;
}

/** API-equivalent cost of the last 30 days against the price of each subscription plan. */
export function PlanValue() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["plan"], queryFn: () => get<PlanData>("/plan", { months: 6 }) });
  const data = q.data;
  const plan = data?.plans.find((p) => p.id === data.current_plan) ?? data?.plans[0];
  const choose = useMutation({
    mutationFn: (id: string) => send("PATCH", "/settings", { plan: id }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["plan"] }).then(() => qc.invalidateQueries({ queryKey: ["settings"] })),
  });

  const build = useCallback(
    (th: Theme) => {
      const months = data?.months ?? [];
      return {
        ...baseOption(th),
        grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
        legend: { show: false },
        tooltip: { ...(baseOption(th).tooltip as object), trigger: "axis", valueFormatter: (v: number) => money(v) },
        xAxis: { type: "category", data: months.map((m) => m.month), ...axisStyle(th), splitLine: { show: false } },
        yAxis: {
          type: "value",
          ...axisStyle(th),
          max: (v: { max: number }) => Math.ceil(Math.max(v.max, plan?.usd_month ?? 0) * 1.15),
          axisLabel: { ...axisStyle(th).axisLabel, showMaxLabel: false, formatter: (v: number) => money(v) },
        },
        series: [{
          name: "API-equivalent",
          type: "bar",
          barMaxWidth: 28,
          data: months.map((m) => ({
            value: m.cost_usd,
            itemStyle: { color: th.series[0], opacity: m.partial ? 0.55 : 1, borderRadius: [3, 3, 0, 0] },
          })),
          markLine: plan ? {
            symbol: "none",
            silent: true,
            lineStyle: { color: th.textSecondary, type: "dashed" },
            label: { formatter: `${plan.name} ${planPrice(plan)}`, color: th.textSecondary, position: "insideEndTop" },
            data: [{ yAxis: plan.usd_month }],
          } : undefined,
        }],
      };
    },
    [data, plan],
  );

  if (!data || !plan) return <Card title="Plan value">{q.error ? <Empty>Plan data unavailable.</Empty> : <Empty>Loading…</Empty>}</Card>;
  const worth = !plan.api_cheaper;
  return (
    <Card title="Plan value"
      subtitle={`Last 30 days at API prices vs what the plan costs, billed ${data.billing === "annual" ? "annually" : "monthly"}`}
      action={
        <select className="input" aria-label="Your plan" value={plan.id} disabled={choose.isPending}
          onChange={(e) => choose.mutate(e.target.value)}>
          {data.plans.map((p) => (
            <option key={p.id} value={p.id}>{p.name} · {planPrice(p)}/mo</option>
          ))}
        </select>
      }>
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <span className="num text-2xl font-semibold">{plan.value_multiple !== null ? `${plan.value_multiple.toFixed(1)}×` : "–"}</span>
        <span className="text-sm" style={{ color: worth ? "var(--good)" : "var(--warning)" }}>
          {worth
            ? `Your usage would cost ${money(data.monthly_usd)}/mo on the API, more than ${plan.name}.`
            : `Pay-as-you-go API would have cost ${money(data.monthly_usd)}/mo, less than ${plan.name}.`}
        </span>
      </div>
      <Chart build={build} height={170} ariaLabel="Bar chart of API-equivalent cost per month against the plan price" />
      <p className="text-xs muted mt-1">
        Compares prices only: plan usage limits aren't published in tokens.
        {data.history_days > 0 && Math.round(data.history_days) < 30 && ` Based on ${Math.round(data.history_days)} days of history, scaled to 30.`}
      </p>
    </Card>
  );
}

const PERIOD_LABELS: Record<BudgetPeriod, string> = { day: "Daily", week: "Weekly", month: "Monthly" };
const STATE_COLORS: Record<BudgetRow["state"], string> = {
  ok: "var(--good)",
  warning: "var(--warning)",
  over: "var(--critical)",
};

/** Spending limits on API-equivalent cost, with progress and a projection to the end of the period. */
export function Budgets() {
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["budgets"],
    queryFn: () => get<{ periods: BudgetPeriod[]; items: BudgetRow[] }>("/budgets"),
  });
  const projects = useQuery({ queryKey: ["projects", 0], queryFn: () => get<ProjectRow[]>("/projects", { days: 0 }) });
  const [adding, setAdding] = useState(false);
  const [period, setPeriod] = useState<BudgetPeriod>("month");
  const [limit, setLimit] = useState("");
  const [project, setProject] = useState("");
  const invalidate = () => qc.invalidateQueries({ queryKey: ["budgets"] });
  const create = useMutation({
    mutationFn: () => send("POST", "/budgets", {
      period, limit_usd: toUsd(Number(limit)), project_id: project ? Number(project) : null,
    }),
    onSuccess: () => {
      setLimit("");
      setAdding(false);
      invalidate();
    },
  });
  const remove = useMutation({ mutationFn: (id: number) => send("DELETE", `/budgets/${id}`), onSuccess: invalidate });
  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (Number(limit) > 0) create.mutate();
  };
  const items = q.data?.items ?? [];

  return (
    <Card title="Budgets" subtitle="API-equivalent spend per period, alerts at 80% and 100%"
      action={<button className="btn" onClick={() => setAdding((a) => !a)} aria-expanded={adding}>{adding ? "Cancel" : "Add budget"}</button>}>
      {adding && (
        <form onSubmit={submit} className="flex flex-wrap items-center gap-2 mb-3" aria-label="New budget">
          <select className="input" aria-label="Period" value={period} onChange={(e) => setPeriod(e.target.value as BudgetPeriod)}>
            {(q.data?.periods ?? ["day", "week", "month"]).map((p) => <option key={p} value={p}>{PERIOD_LABELS[p]}</option>)}
          </select>
          <input className="input w-28" type="number" min="0.01" step="0.01" inputMode="decimal" placeholder={currencySymbol()}
            aria-label="Limit" value={limit} onChange={(e) => setLimit(e.target.value)} required />
          <select className="input" aria-label="Budget project" value={project} onChange={(e) => setProject(e.target.value)}>
            <option value="">All projects</option>
            {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
          </select>
          <button className="btn btn-primary" type="submit" disabled={create.isPending}>Save</button>
          {create.error && <span className="text-xs" style={{ color: "var(--critical)" }}>Could not save the budget.</span>}
        </form>
      )}
      {items.length === 0 ? (
        !adding && <Empty>No budgets yet. Add one to see your progress and get alerts before you overspend.</Empty>
      ) : (
        <ul className="space-y-3">
          {items.map((b) => (
            <li key={b.id} data-testid="budget">
              <div className="flex justify-between items-baseline gap-2 text-sm">
                <span>
                  {PERIOD_LABELS[b.period]} <span className="muted text-xs">· {b.project ?? "All projects"}</span>
                </span>
                <span className="num whitespace-nowrap">
                  {money(b.spent_usd)} <span className="muted">of {money(b.limit_usd)}</span>
                  <button className="ml-2 muted hover:underline text-xs" aria-label={`Delete ${PERIOD_LABELS[b.period].toLowerCase()} budget`}
                    onClick={() => remove.mutate(b.id)}>Remove</button>
                </span>
              </div>
              <div className="h-2 rounded mt-1" style={{ background: "var(--surface-2)" }}>
                <div className="h-2 rounded" style={{ width: `${Math.min(b.ratio ?? 0, 1) * 100}%`, background: STATE_COLORS[b.state] }} />
              </div>
              <div className="text-xs muted mt-1">
                {pct(b.ratio)} used
                {b.projected_usd !== null && ` · heading for ${money(b.projected_usd)}`}
                {b.state === "over" && " · over budget"}
              </div>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
