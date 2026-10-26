import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { get, type CacheData } from "../api";
import { Card, Empty, ErrorBox, Loading, Stat } from "../components/ui";
import { FilterBar, useFilters } from "../filters";
import { dateTime, pct, tokens, truncate, money } from "../format";

function gap(seconds: number | null): string {
  if (seconds === null) return "–";
  if (seconds < 120) return `${Math.round(seconds)}s`;
  if (seconds < 7200) return `${Math.round(seconds / 60)} min`;
  return `${(seconds / 3600).toFixed(1)} h`;
}

export default function Cache() {
  const { days, projectId, device } = useFilters();
  const q = useQuery({
    queryKey: ["cache", days, projectId, device],
    queryFn: () => get<CacheData>("/cache", { days, project_id: projectId, device }),
  });
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Cache</h1>
          <p className="text-sm secondary">
            Prompt caching makes re-reading the conversation cheap. Rebuilds and oversized contexts are where it leaks.
          </p>
        </div>
        <FilterBar />
      </div>
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && <Body data={q.data} />}
    </div>
  );
}

function Body({ data }: { data: CacheData }) {
  const t = data.totals;
  const wasted = data.by_cause.reduce((a, c) => a + c.wasted_usd, 0);
  const maxWaste = Math.max(...data.by_cause.map((c) => c.wasted_usd), 0.0001);
  return (
    <>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <Stat label="Cache hit ratio" value={pct(t.hit_ratio)} hint={`${tokens(t.cache_read)} tokens read from cache`} />
        <Stat label="Saved by caching" value={money(t.saved_usd)} hint="vs. sending every token as fresh input" />
        <Stat label="Spent on cache reads" value={money(t.read_usd)} hint={`${money(t.write_usd)} on cache writes`} />
        <Stat label="Lost to rebuilds" value={money(wasted)}
          hint={`${data.by_cause.reduce((a, c) => a + c.rebuilds, 0)} rebuilds · extra cost of writing vs. reading`} />
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
        <Card title="Why the cache was rebuilt" subtitle="A rebuild rewrites a context the previous call already had cached">
          {data.by_cause.length === 0 ? <Empty>No cache rebuilds in this range.</Empty> : (
            <ul className="space-y-3">
              {data.by_cause.map((c) => (
                <li key={c.cause}>
                  <div className="flex justify-between text-sm gap-3">
                    <span>{c.label}</span>
                    <span className="num whitespace-nowrap">{money(c.wasted_usd)} <span className="muted">· {c.rebuilds}×</span></span>
                  </div>
                  <div className="h-2 rounded mt-1.5" style={{ background: "var(--surface-2)" }}>
                    <div className="h-2 rounded" style={{ width: `${(c.wasted_usd / maxWaste) * 100}%`, background: "var(--accent)" }} />
                  </div>
                  <div className="text-xs muted mt-1">{tokens(c.tokens)} tokens rewritten</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
        <Card title="Biggest contexts" subtitle="Average tokens every main-thread call re-reads, per session">
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>Session</th><th className="r">Calls</th><th className="r">Avg context</th><th className="r">Peak</th></tr>
              </thead>
              <tbody>
                {data.contexts.map((c) => (
                  <tr key={c.session_id}>
                    <td><Link to={`/sessions/${c.session_id}`} className="hover:underline">{truncate(c.title, 60) || c.session_id.slice(0, 8)}</Link></td>
                    <td className="r num">{c.calls}</td>
                    <td className="r num">{tokens(c.avg_context)}</td>
                    <td className="r num">{tokens(c.max_context)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      </div>

      <Card title="Recent rebuilds">
        {data.events.length === 0 ? <Empty>No cache rebuilds in this range.</Empty> : (
          <div className="overflow-x-auto">
            <table className="data-table">
              <thead>
                <tr><th>When</th><th>Session</th><th>Cause</th><th className="r">Idle before</th><th className="r">Rewritten</th><th className="r">Extra cost</th></tr>
              </thead>
              <tbody>
                {data.events.map((e, i) => (
                  <tr key={i}>
                    <td className="secondary whitespace-nowrap">{dateTime(e.ts)}</td>
                    <td><Link to={`/sessions/${e.session_id}`} className="hover:underline">{truncate(e.title, 50) || e.session_id.slice(0, 8)}</Link></td>
                    <td className="secondary">{data.by_cause.find((c) => c.cause === e.cause)?.label ?? e.cause}</td>
                    <td className="r num">{gap(e.gap_seconds)}</td>
                    <td className="r num">{tokens(e.tokens)}</td>
                    <td className="r num">{money(e.wasted_usd)}</td>
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
