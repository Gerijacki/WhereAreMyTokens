import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import { get, type ProjectRow, type SourceRow } from "./api";

const RANGES = [
  { days: 7, label: "7d" },
  { days: 30, label: "30d" },
  { days: 90, label: "90d" },
  { days: 0, label: "All" },
];

/** Time range, project and device filters, kept in the URL so views are shareable. */
export function useFilters() {
  const [params, setParams] = useSearchParams();
  const days = Number(params.get("days") ?? 30);
  const projectId = params.get("project") ? Number(params.get("project")) : undefined;
  const device = params.get("device") || undefined;
  const set = (key: string, value: string | undefined) => {
    const next = new URLSearchParams(params);
    if (value === undefined || value === "") next.delete(key);
    else next.set(key, value);
    setParams(next, { replace: true });
  };
  return {
    days,
    projectId,
    device,
    setDays: (d: number) => set("days", String(d)),
    setProject: (id: number | undefined) => set("project", id === undefined ? undefined : String(id)),
    setDevice: (name: string | undefined) => set("device", name),
  };
}

export function FilterBar({ showProject = true }: { showProject?: boolean }) {
  const { days, projectId, device, setDays, setProject, setDevice } = useFilters();
  const projects = useQuery({
    queryKey: ["projects", 0],
    queryFn: () => get<ProjectRow[]>("/projects", { days: 0 }),
    enabled: showProject,
  });
  const sources = useQuery({
    queryKey: ["sources", 0],
    queryFn: () => get<SourceRow[]>("/sources", { days: 0 }),
  });
  // Only worth a control once a second machine sends data (`wamt agent`), or a link kept a filter.
  const showDevice = (sources.data?.length ?? 0) > 1 || device !== undefined;
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
      {showDevice && (
        <select
          className="input"
          aria-label="Device"
          value={device ?? ""}
          onChange={(e) => setDevice(e.target.value || undefined)}
        >
          <option value="">All devices</option>
          {sources.data?.map((s) => (
            <option key={s.device} value={s.device}>
              {s.device}
            </option>
          ))}
        </select>
      )}
    </div>
  );
}
