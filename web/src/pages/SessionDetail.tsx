import { useCallback, useEffect } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useLocation, useParams } from "react-router-dom";
import { get, send, type SessionDetail as Detail, type SessionEventRow, type TurnRow } from "../api";
import { CATEGORY_LABELS, categoryColor } from "../categories";
import { Chart, axisStyle, baseOption, type Theme } from "../components/Chart";
import { Card, ErrorBox, Loading, Stat } from "../components/ui";
import { dateTime, pct, shortModel, tokens, truncate, money } from "../format";

export default function SessionDetail() {
  const { id } = useParams();
  const { hash } = useLocation();
  const q = useQuery({ queryKey: ["session", id], queryFn: () => get<Detail>(`/sessions/${id}`) });

  useEffect(() => {
    if (q.data && hash) document.getElementById(hash.slice(1))?.scrollIntoView({ block: "center" });
  }, [q.data, hash]);

  if (q.isLoading) return <Loading />;
  if (q.error) return <ErrorBox error={q.error} />;
  if (!q.data) return null;
  return <Body s={q.data} highlight={hash.slice(1)} />;
}

function Body({ s, highlight }: { s: Detail; highlight: string }) {
  const turns = s.turns;
  const buildTurns = useCallback(
    (th: Theme) => ({
      ...baseOption(th),
      grid: { left: 8, right: 16, top: 12, bottom: 8, containLabel: true },
      tooltip: {
        ...(baseOption(th).tooltip as object),
        trigger: "axis",
        axisPointer: { type: "shadow", shadowStyle: { color: th.grid, opacity: 0.5 } },
        formatter: (ps: { dataIndex: number }[]) => {
          const t = turns[ps[0].dataIndex];
          const prompt = truncate(t.prompt, 90).replace(/</g, "&lt;");
          return `<div style="max-width:320px;white-space:normal"><b>#${ps[0].dataIndex + 1}</b> ${prompt}<br/>` +
            `<span style="font-family:monospace">${money(t.cost_usd)} · ${t.api_calls} calls</span></div>`;
        },
      },
      xAxis: { type: "category", data: turns.map((_, i) => `#${i + 1}`), ...axisStyle(th), splitLine: { show: false } },
      yAxis: { type: "value", ...axisStyle(th), axisLabel: { ...axisStyle(th).axisLabel, formatter: (v: number) => money(v) } },
      series: [{
        type: "bar",
        barMaxWidth: 24,
        itemStyle: { color: th.series[0], borderRadius: [4, 4, 0, 0] },
        data: turns.map((t) => t.cost_usd),
      }],
    }),
    [turns],
  );

  return (
    <div className="space-y-4">
      <div>
        <Link to="/sessions" className="text-sm secondary hover:underline">← Sessions</Link>
        <h1 className="text-xl font-semibold mt-1">{s.title || s.id}</h1>
        <div className="flex flex-wrap gap-1.5 mt-2 text-xs">
          {s.project && <span className="chip">{s.project}</span>}
          {s.git_branch && <span className="chip">{s.git_branch}</span>}
          {s.entrypoint && <span className="chip">{s.entrypoint}</span>}
          {s.version && <span className="chip">v{s.version}</span>}
          {s.models.map((m) => <span key={m} className="chip">{shortModel(m)}</span>)}
          <span className="chip">{dateTime(s.started_at)} → {dateTime(s.ended_at)}</span>
        </div>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="API-equivalent cost" value={money(s.cost_usd)} hint={`${s.api_calls} API calls`} />
        <Stat label="Prompts" value={String(turns.length)}
          hint={turns.length ? `${money(s.cost_usd / turns.length)} per prompt` : undefined} />
        <Stat label="Cache hit ratio" value={pct(s.cache_hit_ratio)} hint={`${tokens(s.cache_write)} written to cache`} />
        <Stat label="Output tokens" value={tokens(s.output_tokens)} hint={`${tokens(s.total_tokens)} total`} />
      </div>

      {turns.length > 1 && (
        <Card title="Cost per prompt" subtitle="Hover a bar to see the prompt">
          <Chart build={buildTurns} height={220} ariaLabel="Bar chart of cost per prompt in this session" />
        </Card>
      )}

      {s.events.length > 0 && (
        <Card title="Session events" subtitle="Compactions, session commands and cache rebuilds">
          <ul className="space-y-1.5 text-sm">
            {s.events.map((e, i) => (
              <li key={i} className="flex flex-wrap gap-x-3">
                <span className="muted num text-xs pt-0.5 w-28 shrink-0">{dateTime(e.ts)}</span>
                <span>{eventLabel(e)}</span>
                {e.kind === "cache_rebuild" && (
                  <span className="muted num text-xs pt-0.5">{tokens(e.tokens)} rewritten · {money(e.wasted_usd)} extra</span>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <Card title="Prompts">
        <ol className="divide-y" style={{ borderColor: "var(--border)" }}>
          {turns.map((t, i) => (
            <li key={t.id} id={`turn-${t.id}`} className="py-3 flex gap-4 rounded"
              style={highlight === `turn-${t.id}` ? { background: "var(--surface-2)" } : undefined}>
              <div className="num text-xs muted w-8 shrink-0 pt-0.5">#{i + 1}</div>
              <div className="min-w-0 flex-1">
                <p className="text-sm whitespace-pre-wrap break-words">
                  {truncate(t.prompt, 600) || <span className="muted">(only editor/harness context)</span>}
                </p>
                <div className="flex flex-wrap gap-1 mt-2">
                  <CategoryPicker turn={t} sessionId={s.id} />
                  {t.permission_mode === "plan" && <span className="chip">plan mode</span>}
                  {Object.entries(t.tools).sort((a, b) => b[1] - a[1]).map(([name, n]) => (
                    <span key={name} className="chip">{name} <span className="num">×{n}</span></span>
                  ))}
                </div>
              </div>
              <div className="text-right shrink-0">
                <div className="num text-sm font-medium">{money(t.cost_usd)}</div>
                <div className="num text-xs muted">{tokens(t.total_tokens)} tok</div>
                <div className="text-xs muted">{dateTime(t.ts)}</div>
              </div>
            </li>
          ))}
        </ol>
      </Card>
    </div>
  );
}

const CAUSE_LABELS: Record<string, string> = {
  idle_expired: "Cache rebuilt after the cache expired during a pause",
  compaction: "Cache rebuilt after compaction",
  model_switch: "Cache rebuilt after switching models",
  prefix_change: "Cache rebuilt: the start of the prompt changed",
};

function eventLabel(e: SessionEventRow): string {
  if (e.kind === "compact") return `Context compacted (${e.cause ?? "auto"}, ${tokens(e.tokens)} before)`;
  if (e.kind === "command") return `Ran ${e.cause}`;
  return CAUSE_LABELS[e.cause ?? ""] ?? "Cache rebuilt";
}

function CategoryPicker({ turn, sessionId }: { turn: TurnRow; sessionId: string }) {
  const qc = useQueryClient();
  const save = useMutation({
    mutationFn: (category: string | null) => send("PATCH", `/turns/${turn.id}`, { category }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["session", sessionId] });
      qc.invalidateQueries({ queryKey: ["categories"] });
    },
  });
  const c = turn.category ?? "chat";
  const manual = turn.category_source === "manual";
  const why = Object.entries(turn.category_scores)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([k, v]) => `${k} ${v}`)
    .join(", ");
  return (
    <label className="chip cursor-pointer" title={manual ? "Set by you" : `Automatic. Scores: ${why}`}>
      <span aria-hidden style={{ width: 8, height: 8, borderRadius: 2, background: categoryColor(c) }} />
      <select
        aria-label="Category"
        className="bg-transparent outline-none cursor-pointer"
        value={manual ? c : "auto"}
        onChange={(e) => save.mutate(e.target.value === "auto" ? null : e.target.value)}
      >
        <option value="auto">{manual ? "Automatic" : `${CATEGORY_LABELS[c] ?? c} (auto)`}</option>
        {Object.keys(CATEGORY_LABELS)
          .filter((k) => k !== "uncategorized")
          .map((k) => (
            <option key={k} value={k}>{CATEGORY_LABELS[k]}</option>
          ))}
      </select>
    </label>
  );
}
