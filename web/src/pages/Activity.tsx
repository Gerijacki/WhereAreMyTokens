import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { get, type CategoriesData, type LimitsData } from "../api";
import { CHART_GROUPS, CategoryChip, categoryColor, chartGroup, groupLabel } from "../categories";
import { Chart, axisStyle, baseOption, type Theme } from "../components/Chart";
import { Card, Empty, ErrorBox, Loading, Stat } from "../components/ui";
import { FilterBar, useFilters } from "../filters";
import { continuousDays, pct, tokens, money } from "../format";

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function Activity() {
  const { days, projectId } = useFilters();
  const cats = useQuery({
    queryKey: ["categories", days, projectId],
    queryFn: () => get<CategoriesData>("/categories", { days, project_id: projectId }),
  });
  const limits = useQuery({
    queryKey: ["limits", days, projectId],
    queryFn: () => get<LimitsData>("/limits", { days: days || 365, project_id: projectId }),
  });

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Activity</h1>
          <p className="text-sm secondary">What kind of work the tokens went to, and when you spend them.</p>
        </div>
        <FilterBar />
      </div>
      {(cats.isLoading || limits.isLoading) && <Loading />}
      {cats.error && <ErrorBox error={cats.error} />}
      {cats.data && <CategoriesSection data={cats.data} />}
      {limits.error && <ErrorBox error={limits.error} />}
      {limits.data && <LimitsSection data={limits.data} />}
    </div>
  );
}

function CategoriesSection({ data }: { data: CategoriesData }) {
  const total = data.by_category.reduce((a, c) => a + c.cost_usd, 0) || 1;
  const build = useCallback(
    (th: Theme) => {
      const days = continuousDays(data.daily.map((d) => d.day));
      const groups = CHART_GROUPS.filter((g) => data.daily.some((d) => chartGroup(d.category) === g));
      const cost = new Map<string, number>();
      for (const d of data.daily) {
        const k = `${d.day}|${chartGroup(d.category)}`;
        cost.set(k, (cost.get(k) ?? 0) + d.cost_usd);
      }
      return {
        ...baseOption(th),
        tooltip: {
          ...(baseOption(th).tooltip as object),
          trigger: "axis",
          axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.5 } },
          valueFormatter: (v: number) => money(v),
        },
        legend: { ...(baseOption(th).legend as object), data: groups.map(groupLabel) },
        xAxis: { type: "category", data: days, ...axisStyle(th), splitLine: { show: false } },
        yAxis: { type: "value", ...axisStyle(th), axisLabel: { ...axisStyle(th).axisLabel, formatter: (v: number) => money(v) } },
        series: groups.map((g) => ({
          name: groupLabel(g),
          type: "bar",
          stack: "cost",
          barMaxWidth: 28,
          itemStyle: { color: categoryColor(g, th), borderColor: th.surface, borderWidth: 1, borderRadius: 2 },
          emphasis: { focus: "series" },
          data: days.map((d) => cost.get(`${d}|${g}`) ?? 0),
        })),
      };
    },
    [data],
  );

  if (data.by_category.length === 0) return <Empty>No categorized prompts in this range.</Empty>;
  return (
    <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
      <Card title="Daily cost by work category" subtitle="Each prompt is categorized from its wording, tools and commands"
        className="xl:col-span-2">
        <Chart build={build} ariaLabel="Stacked bar chart of daily cost by work category" />
      </Card>
      <Card title="Categories">
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr><th>Category</th><th className="r">Prompts</th><th className="r">Per prompt</th><th className="r">Cost</th><th className="r">Share</th></tr>
            </thead>
            <tbody>
              {data.by_category.map((c) => (
                <tr key={c.category}>
                  <td><CategoryChip category={c.category} /></td>
                  <td className="r num">{c.prompts}</td>
                  <td className="r num">{money(c.cost_per_prompt)}</td>
                  <td className="r num">{money(c.cost_usd)}</td>
                  <td className="r num">{pct(c.cost_usd / total)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  );
}

function LimitsSection({ data }: { data: LimitsData }) {
  const c = data.current;
  const buildBlocks = useCallback(
    (th: Theme) => {
      const blocks = data.blocks.slice(-60);
      const fmt = (iso: string) =>
        new Date(iso).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit" });
      return {
        ...baseOption(th),
        grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
        tooltip: {
          ...(baseOption(th).tooltip as object),
          trigger: "axis",
          axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.5 } },
          formatter: (ps: { dataIndex: number }[]) => {
            const b = blocks[ps[0].dataIndex];
            return `<b>${fmt(b.start)}</b> · ${data.block_hours}h block<br/>` +
              `<span style="font-family:monospace">${money(b.cost_usd)} · ${b.calls} calls · ${tokens(b.tokens)} new tokens</span><br/>` +
              `<span style="opacity:.75">active ${b.active_minutes} min</span>`;
          },
        },
        xAxis: { type: "category", data: blocks.map((b) => fmt(b.start)), ...axisStyle(th), splitLine: { show: false } },
        yAxis: { type: "value", ...axisStyle(th), axisLabel: { ...axisStyle(th).axisLabel, formatter: (v: number) => money(v) } },
        series: [{
          type: "bar",
          barMaxWidth: 22,
          itemStyle: { color: th.series[0], borderRadius: [4, 4, 0, 0] },
          data: blocks.map((b) => b.cost_usd),
          markLine: {
            silent: true,
            symbol: "none",
            lineStyle: { color: th.muted, type: "dashed", width: 1 },
            label: { color: th.muted, fontSize: 11, formatter: "median", position: "insideEndTop" },
            data: [{ yAxis: data.median_block_cost_usd }],
          },
        }],
      };
    },
    [data],
  );

  const buildHeat = useCallback(
    (th: Theme) => {
      const cells: [number, number, number][] = [];
      let max = 0;
      data.heatmap.forEach((row, wd) => row.forEach((v, h) => {
        cells.push([h, wd, v]);
        max = Math.max(max, v);
      }));
      return {
        ...baseOption(th),
        grid: { left: 8, right: 8, top: 8, bottom: 48, containLabel: true },
        tooltip: {
          ...(baseOption(th).tooltip as object),
          formatter: (p: { value: [number, number, number] }) =>
            `${WEEKDAYS[p.value[1]]} ${String(p.value[0]).padStart(2, "0")}:00 · <b>${money(p.value[2])}</b>`,
        },
        xAxis: { type: "category", data: Array.from({ length: 24 }, (_, h) => String(h)), ...axisStyle(th),
          splitLine: { show: false }, axisLine: { show: false } },
        yAxis: { type: "category", data: WEEKDAYS, inverse: true, ...axisStyle(th), splitLine: { show: false },
          axisLine: { show: false } },
        visualMap: {
          min: 0, max: max || 1, calculable: false, orient: "horizontal", left: "center", bottom: 0,
          itemWidth: 10, itemHeight: 120, textStyle: { color: th.muted, fontSize: 11 },
          formatter: (v: number) => money(v),
          inRange: { color: [th.surface2, th.series[0]] },
        },
        series: [{
          type: "heatmap",
          data: cells,
          itemStyle: { borderColor: th.surface, borderWidth: 2, borderRadius: 3 },
          emphasis: { itemStyle: { borderColor: th.text, borderWidth: 1 } },
        }],
      };
    },
    [data],
  );

  const buildWeekly = useCallback(
    (th: Theme) => ({
      ...baseOption(th),
      grid: { left: 8, right: 16, top: 16, bottom: 8, containLabel: true },
      tooltip: { ...(baseOption(th).tooltip as object), trigger: "axis", valueFormatter: (v: number) => money(v),
        axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.5 } } },
      xAxis: { type: "category", data: data.weekly.map((w) => `wk ${w.week.slice(5)}`), ...axisStyle(th),
        splitLine: { show: false } },
      yAxis: { type: "value", ...axisStyle(th), axisLabel: { ...axisStyle(th).axisLabel, formatter: (v: number) => money(v) } },
      series: [{ type: "bar", barMaxWidth: 28, itemStyle: { color: th.series[0], borderRadius: [4, 4, 0, 0] },
        data: data.weekly.map((w) => w.cost_usd) }],
    }),
    [data],
  );

  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Current 5-hour block" value={c ? money(c.cost_usd) : "Idle"}
          hint={c ? `${c.calls} calls · ${c.minutes_left} min left` : "No activity in the last 5 hours"} />
        <Stat label="Burn rate" value={c ? `${money(c.burn_usd_per_hour)}/h` : "–"}
          hint={c ? `Projected ${money(c.projected_cost_usd)} by block end` : undefined} />
        <Stat label="Median block" value={money(data.median_block_cost_usd)} hint={`${data.blocks.length} blocks in range`} />
        <Stat label="Heaviest block" value={money(data.peak_block_cost_usd)}
          hint={c && data.peak_block_cost_usd ? `Current is ${pct(c.projected_cost_usd / data.peak_block_cost_usd)} of it (projected)` : "Your own high-water mark"} />
      </div>
      <Card title="5-hour usage blocks"
        subtitle={`Blocks start at the hour of the first request (${data.timezone}). Anthropic doesn't publish the exact limits, so compare against your own history.`}>
        {data.blocks.length === 0 ? <Empty>No usage in this range.</Empty> :
          <Chart build={buildBlocks} height={240} ariaLabel="Bar chart of API-equivalent cost per 5-hour block" />}
      </Card>
      <div className="grid grid-cols-1 xl:grid-cols-3 gap-3">
        <Card title="When you work" subtitle="Cost by weekday and hour" className="xl:col-span-2">
          <Chart build={buildHeat} height={270} ariaLabel="Heatmap of cost by weekday and hour" />
        </Card>
        <Card title="Weekly cost" subtitle="Weeks start on Monday">
          <Chart build={buildWeekly} height={270} ariaLabel="Bar chart of weekly cost" />
        </Card>
      </div>
    </>
  );
}
