import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get, type Overview as OverviewData, type TopTurn } from "../api";
import { CategoryChip } from "../categories";
import { Chart, axisStyle, baseOption, type Theme } from "../components/Chart";
import { CategoryBreakdown, TopInsights } from "../components/OverviewExtras";
import { Budgets, PlanValue } from "../components/Spend";
import { TelemetryCard } from "../components/Telemetry";
import { Card, Empty, ErrorBox, Loading, Stat } from "../components/ui";
import { FilterBar, useFilters } from "../filters";
import { continuousDays, dateTime, pct, shortModel, tokens, truncate, money } from "../format";
import { useModelColors } from "../modelColors";

const KINDS = [
  { key: "cache_read", label: "Cache read" },
  { key: "cache_write", label: "Cache write" },
  { key: "output", label: "Output" },
  { key: "input", label: "Input (uncached)" },
] as const;

export default function Overview() {
  const { days, projectId, device } = useFilters();
  const q = useQuery({
    queryKey: ["overview", days, projectId, device],
    queryFn: () => get<OverviewData>("/overview", { days, project_id: projectId, device }),
  });
  const top = useQuery({
    queryKey: ["top-turns", days, projectId, device],
    queryFn: () => get<TopTurn[]>("/turns/top", { days, project_id: projectId, device, limit: 10 }),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Overview</h1>
          <p className="text-sm secondary">What your Claude Code usage would cost at API list prices.</p>
        </div>
        <FilterBar />
      </div>
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && (q.data.totals.api_calls === 0 ? (
        <Empty>No usage in this range yet. The collector picks up new transcripts every few seconds.</Empty>
      ) : (
        <OverviewBody data={q.data} top={top.data ?? []} />
      ))}
      <TelemetryCard days={days} />
    </div>
  );
}

function OverviewBody({ data, top }: { data: OverviewData; top: TopTurn[] }) {
  const t = data.totals;
  const colorOf = useModelColors();
  const main = data.by_thread.find((r) => r.thread === "main");
  const sub = data.by_thread.find((r) => r.thread === "subagents");

  const buildDaily = useCallback(
    (th: Theme) => {
      const days = continuousDays(data.daily.map((d) => d.day));
      const models = data.by_model.map((m) => m.model);
      const cost = new Map(data.daily_by_model.map((r) => [`${r.day}|${r.model}`, r.cost_usd]));
      return {
        ...baseOption(th),
        tooltip: {
          ...(baseOption(th).tooltip as object),
          trigger: "axis",
          axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.5 } },
          valueFormatter: (v: number) => money(v),
        },
        legend: { ...(baseOption(th).legend as object), data: models.map(shortModel) },
        xAxis: { type: "category", data: days, ...axisStyle(th), splitLine: { show: false } },
        yAxis: { type: "value", ...axisStyle(th), axisLabel: { ...axisStyle(th).axisLabel, formatter: (v: number) => money(v) } },
        series: models.map((m) => ({
          name: shortModel(m),
          type: "bar",
          stack: "cost",
          barMaxWidth: 28,
          itemStyle: { color: colorOf(m, th), borderColor: th.surface, borderWidth: 1, borderRadius: 2 },
          emphasis: { focus: "series" },
          data: days.map((d) => cost.get(`${d}|${m}`) ?? 0),
        })),
      };
    },
    [data, colorOf],
  );

  const kindTokens: Record<string, number> = {
    cache_read: t.cache_read,
    cache_write: t.cache_write,
    output: t.output_tokens,
    input: t.input_tokens,
  };
  const kindCostTotal = Object.values(data.cost_by_kind).reduce((a, b) => a + b, 0) || 1;

  const buildKinds = useCallback(
    (th: Theme) => ({
      ...baseOption(th),
      grid: { left: 8, right: 56, top: 4, bottom: 4, containLabel: true },
      tooltip: { ...(baseOption(th).tooltip as object), trigger: "item", valueFormatter: (v: number) => money(v) },
      xAxis: { type: "value", show: false },
      yAxis: {
        type: "category",
        inverse: true,
        data: KINDS.map((k) => k.label),
        ...axisStyle(th),
        axisLine: { show: false },
        axisLabel: { color: th.textSecondary, fontSize: 12 },
      },
      series: [{
        type: "bar",
        barWidth: 18,
        itemStyle: { color: th.series[0], borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: "right", color: th.textSecondary, formatter: (p: { value: number }) => money(p.value) },
        data: KINDS.map((k) => data.cost_by_kind[k.key]),
      }],
    }),
    [data],
  );

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="API-equivalent cost" value={money(t.cost_usd)}
          hint={t.unpriced_calls ? `${t.unpriced_calls} calls on unpriced models` : `${t.api_calls.toLocaleString()} API calls`} />
        <Stat label="Tokens processed" value={tokens(t.total_tokens)} hint={`${tokens(t.output_tokens)} output`} />
        <Stat label="Cache hit ratio" value={pct(t.cache_hit_ratio)} hint="cache reads ÷ prompt tokens" />
        <Stat label="Prompts" value={t.prompts.toLocaleString()}
          hint={`${t.sessions} sessions · ${money(t.prompts ? t.cost_usd / t.prompts : 0)} per prompt`} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <PlanValue />
        <Budgets />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <Card title="Daily cost by model" subtitle="API-equivalent USD per day" className="xl:col-span-2">
          <Chart build={buildDaily} ariaLabel="Stacked bar chart of daily API-equivalent cost by model" />
        </Card>
        <Card title="Where the cost comes from" subtitle="Cost by token kind">
          <Chart build={buildKinds} height={150} ariaLabel="Bar chart of cost by token kind" />
          <table className="data-table mt-2">
            <thead>
              <tr><th>Kind</th><th className="r">Tokens</th><th className="r">Share</th></tr>
            </thead>
            <tbody>
              {KINDS.map((k) => (
                <tr key={k.key}>
                  <td>{k.label}</td>
                  <td className="r num">{tokens(kindTokens[k.key])}</td>
                  <td className="r num">{pct(data.cost_by_kind[k.key] / kindCostTotal)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <Card title="Models" className="xl:col-span-2">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Model</th><th className="r">Calls</th><th className="r">Output</th>
                  <th className="r">Cache read</th><th className="r">Cache write</th>
                  <th className="r">Hit ratio</th><th className="r">Cost</th>
                </tr>
              </thead>
              <tbody>
                {data.by_model.map((m) => (
                  <tr key={m.model}>
                    <td><ModelName model={m.model} /></td>
                    <td className="r num">{m.api_calls.toLocaleString()}</td>
                    <td className="r num">{tokens(m.output_tokens)}</td>
                    <td className="r num">{tokens(m.cache_read)}</td>
                    <td className="r num">{tokens(m.cache_write)}</td>
                    <td className="r num">{pct(m.cache_hit_ratio)}</td>
                    <td className="r num">{money(m.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <div className="space-y-3">
          <Card title="Main thread vs subagents">
            <ThreadRow label="Main thread" cost={main?.cost_usd ?? 0} total={t.cost_usd} calls={main?.api_calls ?? 0} />
            <ThreadRow label="Subagents" cost={sub?.cost_usd ?? 0} total={t.cost_usd} calls={sub?.api_calls ?? 0} />
          </Card>
          {data.by_device.length > 1 && (
            <Card title="By device" subtitle="Machines sending usage with wamt agent">
              {data.by_device.map((d) => (
                <ThreadRow key={d.device} label={d.device} cost={d.cost_usd} total={t.cost_usd} calls={d.api_calls} />
              ))}
            </Card>
          )}
        </div>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <CategoryBreakdown />
        <TopInsights />
      </div>

      <Card title="Most expensive prompts" subtitle="Each prompt includes all the tool calls and subagents it triggered">
        {top.length === 0 ? <Empty>No prompts in this range.</Empty> : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>Prompt</th><th>Category</th><th>Project</th><th>When</th><th className="r">Calls</th><th className="r">Cost</th></tr>
              </thead>
              <tbody>
                {top.map((r) => (
                  <tr key={r.id}>
                    <td className="min-w-[280px]">
                      <Link to={`/sessions/${r.session_id}#turn-${r.id}`} className="hover:underline">
                        {truncate(r.prompt, 140) || <span className="muted">(empty)</span>}
                      </Link>
                    </td>
                    <td><CategoryChip category={r.category} /></td>
                    <td className="secondary whitespace-nowrap">{r.project}</td>
                    <td className="secondary whitespace-nowrap">{dateTime(r.ts)}</td>
                    <td className="r num">{r.api_calls}</td>
                    <td className="r num">{money(r.cost_usd)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

function ModelName({ model }: { model: string }) {
  const colorOf = useModelColors();
  return (
    <span className="inline-flex items-center gap-2 whitespace-nowrap">
      <span aria-hidden style={{ width: 10, height: 10, borderRadius: 3, background: colorOf(model) }} />
      {shortModel(model)}
    </span>
  );
}

function ThreadRow({ label, cost, total, calls }: { label: string; cost: number; total: number; calls: number }) {
  const share = total ? cost / total : 0;
  return (
    <div className="py-2">
      <div className="flex justify-between text-sm">
        <span>{label}</span>
        <span className="num">{money(cost)} <span className="muted">· {pct(share)}</span></span>
      </div>
      <div className="h-2 rounded mt-1.5" style={{ background: "var(--surface-2)" }}>
        <div className="h-2 rounded" style={{ width: `${share * 100}%`, background: "var(--accent)" }} />
      </div>
      <div className="text-xs muted mt-1">{calls.toLocaleString()} API calls</div>
    </div>
  );
}
