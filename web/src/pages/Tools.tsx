import { useCallback } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get, type ToolsData } from "../api";
import { Chart, axisStyle, baseOption, type Theme } from "../components/Chart";
import { Card, Empty, ErrorBox, Loading } from "../components/ui";
import { FilterBar, useFilters } from "../filters";
import { pct, tokens, truncate } from "../format";

export default function Tools() {
  const { days, projectId } = useFilters();
  const q = useQuery({
    queryKey: ["tools", days, projectId],
    queryFn: () => get<ToolsData>("/tools", { days, project_id: projectId }),
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Tools</h1>
          <p className="text-sm secondary">
            Which tools Claude calls, how often they fail, and how much output they push into the context.
          </p>
        </div>
        <FilterBar />
      </div>
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && (q.data.by_tool.length === 0 ? <Empty>No tool calls in this range.</Empty> : <Body data={q.data} />)}
    </div>
  );
}

function Body({ data }: { data: ToolsData }) {
  const top = data.by_tool.slice(0, 12);
  const build = useCallback(
    (th: Theme) => ({
      ...baseOption(th),
      grid: { left: 8, right: 64, top: 4, bottom: 4, containLabel: true },
      tooltip: {
        ...(baseOption(th).tooltip as object),
        trigger: "item",
        formatter: (p: { dataIndex: number }) => {
          const t = top[p.dataIndex];
          return `<b>${t.name}</b><br/><span style="font-family:monospace">${t.calls.toLocaleString()} calls · ` +
            `${tokens(t.result_tokens)} output tokens · ${pct(t.error_rate)} errors</span>`;
        },
      },
      xAxis: { type: "value", show: false },
      yAxis: { type: "category", inverse: true, data: top.map((t) => t.name), ...axisStyle(th), axisLine: { show: false },
        axisLabel: { color: th.textSecondary, fontSize: 12 } },
      series: [{
        type: "bar",
        barWidth: 14,
        itemStyle: { color: th.series[0], borderRadius: [0, 4, 4, 0] },
        label: { show: true, position: "right", color: th.textSecondary, fontSize: 11,
          formatter: (p: { value: number }) => tokens(p.value) },
        data: top.map((t) => t.result_tokens),
      }],
    }),
    [top],
  );

  return (
    <>
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <Card title="Output pushed into context" subtitle="Tokens returned by each tool (≈ characters ÷ 4)">
          <Chart build={build} height={Math.max(160, top.length * 28)} ariaLabel="Bar chart of tool output tokens by tool" />
        </Card>
        <Card title="All tools">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>Tool</th><th className="r">Calls</th><th className="r">Errors</th><th className="r">Avg output</th><th className="r">Sessions</th></tr>
              </thead>
              <tbody>
                {data.by_tool.map((t) => (
                  <tr key={t.name}>
                    <td className="num text-xs">{t.name}</td>
                    <td className="r num">{t.calls.toLocaleString()}</td>
                    <td className="r num" style={t.error_rate > 0.1 ? { color: "var(--critical)" } : undefined}>
                      {t.errors ? `${t.errors} · ${pct(t.error_rate)}` : "–"}
                    </td>
                    <td className="r num">{tokens(t.avg_result_tokens)}</td>
                    <td className="r num">{t.sessions}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <Card title="Most-run shell commands" subtitle="Normalized: `cd` prefixes, output filters and arguments removed">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>Command</th><th className="r">Runs</th><th className="r">Prompts</th><th className="r">Failed</th><th className="r">Avg output</th></tr>
              </thead>
              <tbody>
                {data.commands.map((c) => (
                  <tr key={c.signature}>
                    <td className="num text-xs break-all">{c.signature}</td>
                    <td className="r num">{c.calls}</td>
                    <td className="r num">{c.prompts}</td>
                    <td className="r num">{c.errors || "–"}</td>
                    <td className="r num">{tokens(c.avg_result_tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
        <Card title="Most-read files" subtitle="Files Claude opens again and again are candidates for a CLAUDE.md summary">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>File</th><th className="r">Reads</th><th className="r">Sessions</th><th className="r">Avg size</th></tr>
              </thead>
              <tbody>
                {data.files.map((f) => (
                  <tr key={f.path}>
                    <td className="num text-xs break-all">{f.path}</td>
                    <td className="r num">{f.reads}</td>
                    <td className="r num">{f.sessions}</td>
                    <td className="r num">{tokens(f.avg_result_tokens)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card title="Largest single results" subtitle="Each of these stays in the conversation and is re-read by every later call">
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead>
              <tr><th>Tool</th><th>Target</th><th className="r">Tokens</th><th></th></tr>
            </thead>
            <tbody>
              {data.biggest_results.map((b) => (
                <tr key={b.id}>
                  <td className="num text-xs">{b.name}</td>
                  <td className="num text-xs break-all">{truncate(b.target, 140) || "–"}</td>
                  <td className="r num">{tokens(b.result_tokens)}</td>
                  <td className="r whitespace-nowrap">
                    <Link className="text-xs hover:underline secondary"
                      to={`/sessions/${b.session_id}${b.turn_id ? `#turn-${b.turn_id}` : ""}`}>session →</Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Card>
    </>
  );
}
