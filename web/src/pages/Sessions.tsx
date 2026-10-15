import { useQuery } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { get, type SessionRow } from "../api";
import { Card, Empty, ErrorBox, Loading } from "../components/ui";
import { FilterBar, useFilters } from "../filters";
import { dateTime, pct, tokens, truncate, usd } from "../format";

const SORTS = [
  { key: "recent", label: "Recent" },
  { key: "cost", label: "Cost" },
  { key: "tokens", label: "Tokens" },
];

export default function Sessions() {
  const { days, projectId } = useFilters();
  const [params, setParams] = useSearchParams();
  const sort = params.get("sort") ?? "recent";
  const q = useQuery({
    queryKey: ["sessions", days, projectId, sort],
    queryFn: () => get<SessionRow[]>("/sessions", { days, project_id: projectId, sort, limit: 200 }),
  });

  const setSort = (s: string) => {
    const next = new URLSearchParams(params);
    next.set("sort", s);
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Sessions</h1>
          <p className="text-sm secondary">Every Claude Code conversation, with its API-equivalent cost.</p>
        </div>
        <div className="flex flex-wrap gap-2">
          <div className="seg" role="group" aria-label="Sort by">
            {SORTS.map((s) => (
              <button key={s.key} aria-pressed={sort === s.key} onClick={() => setSort(s.key)}>{s.label}</button>
            ))}
          </div>
          <FilterBar />
        </div>
      </div>
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && (
        <Card>
          {q.data.length === 0 ? <Empty>No sessions in this range.</Empty> : (
            <div className="overflow-x-auto">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Session</th><th>Project</th><th>Last activity</th><th className="r">Calls</th>
                    <th className="r">Tokens</th><th className="r">Hit ratio</th><th className="r">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {q.data.map((s) => (
                    <tr key={s.id}>
                      <td className="min-w-[240px]">
                        <Link to={`/sessions/${s.id}`} className="hover:underline font-medium">
                          {truncate(s.title, 90) || <span className="muted num">{s.id.slice(0, 8)}</span>}
                        </Link>
                        <div className="flex gap-1 mt-1">
                          {s.git_branch && <span className="chip">{s.git_branch}</span>}
                          {s.entrypoint && <span className="chip">{s.entrypoint}</span>}
                        </div>
                      </td>
                      <td className="secondary whitespace-nowrap">{s.project}</td>
                      <td className="secondary whitespace-nowrap">{dateTime(s.ended_at)}</td>
                      <td className="r num">{s.api_calls.toLocaleString()}</td>
                      <td className="r num">{tokens(s.total_tokens)}</td>
                      <td className="r num">{pct(s.cache_hit_ratio)}</td>
                      <td className="r num">{usd(s.cost_usd)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      )}
    </div>
  );
}
