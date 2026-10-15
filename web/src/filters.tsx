import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get, type ProjectRow } from "./api";

const RANGES = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
  { days: 0, label: "All" },
];

/** Time range + project filter, kept in the URL so views are shareable. */
export function useFilters() {
  const [params, setParams] = useSearchParams();
  const days = Number(params.get("days") ?? 30);
  const projectId = params.get("project") ? Number(params.get("project")) : undefined;
  const set = (key: string, value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value === undefined || value === "") next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };
  return {
    days,
    projectId,
    setDays: (d: number) => set("days", String(d)),
    setProject: (id: number | undefined) => set("project", id === undefined ? undefined : String(id)),
  };
}

export function FilterBar({ showProject = true }: { showProject?: boolean }) {
  const { days, projectId, setDays, setProject } = useFilters();
  const projects = useQuery({
    queryKey: ["projects", 0],
    queryFn: () => get<ProjectRow[]>("/projects", { days: 0 }),
    enabled: showProject,
  });
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="seg" role="group" aria-label="Time range">
        {RANGES.map((r) => (
          <button key={r.days} aria-pressed={days === r.days} onClick={() => setDays(r.days)}>
            {r.label}
          </button>
        ))}
      </div>
      {showProject && (
        <select
          className="input"
          aria-label="Project"
          value={projectId ?? ""}
          onChange={(e) => setProject(e.target.value ? Number(e.target.value) : undefined)}
        >
          <option value="">All projects</option>
          {projects.data?.map((p) => (
            <option key={p.id} value={p.id}>
              {p.name}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
