import { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useSearchParams } from "react-router-dom";
import { get, send, type Insight, type InsightsData } from "../api";
import { Card, Empty, ErrorBox, Loading, Stat } from "../components/ui";
import { useFilters } from "../filters";
import { dateTime, tokens, truncate, money } from "../format";

export const TYPE_LABELS: Record<string, string> = {
  large_context: "Large context",
  cache_rebuild: "Cache rebuild",
  context_bloat: "Context bloat",
  command_sequence: "Repeated sequence",
  noisy_command: "Noisy output",
  fix_loop: "Fix loop",
  file_rereads: "Re-read files",
  repeated_prompt: "Repeated prompt",
  model_fit: "Model fit",
  allowlist: "Permissions",
};

const ARTIFACT_LABELS: Record<string, string> = {
  skill: "Skill",
  command: "Slash command",
  agent: "Subagent",
  settings: "Settings (merge)",
  claude_md: "CLAUDE.md section",
  tip: "How to fix",
};

const STATUSES = [
  { key: "open", label: "Open" },
  { key: "done", label: "Done" },
  { key: "dismissed", label: "Dismissed" },
] as const;

export default function Insights() {
  const { projectId } = useFilters();
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "open";
  const openId = params.get("open");
  const typeFilter = params.get("type") ?? "";
  const qc = useQueryClient();
  const q = useQuery({
    queryKey: ["insights", status, projectId],
    queryFn: () => get<InsightsData>("/insights", { status, project_id: projectId }),
  });
  const refresh = useMutation({
    mutationFn: () => send("POST", "/insights/refresh"),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insights"] }),
  });
  const visible = (q.data?.items ?? []).filter((i) => !typeFilter || i.type === typeFilter);
  const types = [...new Set((q.data?.items ?? []).map((i) => i.type))];
  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  const setStatus = (s: string) => {
    const next = new URLSearchParams(params);
    next.set("status", s);
    setParams(next, { replace: true });
  };

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Insights</h1>
          <p className="text-sm secondary">
            Patterns in your sessions that cost tokens, each with a ready-to-paste fix for Claude Code.
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="seg" role="group" aria-label="Status">
            {STATUSES.map((s) => (
              <button key={s.key} aria-pressed={status === s.key} onClick={() => setStatus(s.key)}>
                {s.label}{q.data ? ` · ${q.data.summary[s.key]}` : ""}
              </button>
            ))}
          </div>
          <select className="input" aria-label="Insight type" value={typeFilter}
            onChange={(e) => setParam("type", e.target.value)}>
            <option value="">All types</option>
            {types.map((t) => <option key={t} value={t}>{TYPE_LABELS[t] ?? t}</option>)}
          </select>
          <button className="btn" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
            {refresh.isPending ? "Analyzing…" : "Re-analyze"}
          </button>
        </div>
      </div>
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
            <Stat label="Potential savings" value={`${money(q.data.summary.open_usd_month)}/mo`}
              hint="API-equivalent, open insights, rough estimate" />
            <Stat label="Open" value={String(q.data.summary.open)}
              hint={`${q.data.items.filter((i) => i.severity === "high").length} high impact`} />
            <Stat label="Realized savings" value={`${money(q.data.summary.realized_usd_month)}/mo`}
              hint={`${q.data.summary.done} done${q.data.summary.measuring ? ` · ${q.data.summary.measuring} measuring` : ""} · ${q.data.summary.dismissed} dismissed`} />
            <Stat label="Last analysis" value={q.data.refreshed_at ? dateTime(q.data.refreshed_at) : "–"}
              hint="Re-runs every 10 min while you work" />
          </div>
          {visible.length === 0 ? (
            <Empty>{status === "open" ? "Nothing to fix right now." : `No ${status} insights.`}</Empty>
          ) : (
            <div className="space-y-3">
              {visible.map((i) => <InsightCard key={i.id} insight={i} defaultOpen={i.id === openId} />)}
            </div>
          )}
        </>
      )}
    </div>
  );
}

function Severity({ level }: { level: Insight["severity"] }) {
  const map = {
    high: { color: "var(--critical)", icon: "▲", label: "High impact" },
    medium: { color: "var(--warning)", icon: "◆", label: "Medium" },
    low: { color: "var(--text-muted)", icon: "●", label: "Low" },
  }[level];
  return (
    <span className="chip" style={{ color: map.color, borderColor: "currentColor" }}>
      <span aria-hidden>{map.icon}</span>
      <span style={{ color: "var(--text-secondary)" }}>{map.label}</span>
    </span>
  );
}

/** What fixing the pattern actually saved, measured on the data recorded since it was marked done. */
function Realized({ insight: i }: { insight: Insight }) {
  const estimate = i.baseline_usd_month ?? i.est_usd_month;
  if (i.realized_usd_month === null) {
    return (
      <div className="text-right shrink-0" title="Realized savings need a week of data after you mark an insight done">
        <div className="text-sm font-semibold">Measuring…</div>
        <div className="text-xs muted">done {dateTime(i.done_at)}</div>
        <div className="text-xs muted num">estimated {money(estimate)}/mo</div>
      </div>
    );
  }
  return (
    <div className="text-right shrink-0"
      title="Compared with the estimate when you marked it done, adjusted for how much you used Claude Code since">
      <div className="num text-lg font-semibold" style={{ color: "var(--good)" }}>{money(i.realized_usd_month)}/mo</div>
      <div className="text-xs muted">realized saving</div>
      <div className="text-xs muted num">
        estimated {money(estimate)}/mo{i.residual_usd_month ? ` · still ${money(i.residual_usd_month)}/mo` : ""}
      </div>
    </div>
  );
}

export function InsightCard({ insight: i, compact = false, defaultOpen = false }: {
  insight: Insight;
  compact?: boolean;
  defaultOpen?: boolean;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(defaultOpen);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = ref.current;
    if (defaultOpen && el && el.getBoundingClientRect().top > window.innerHeight * 0.6) el.scrollIntoView({ block: "start" });
  }, [defaultOpen]);
  const [copied, setCopied] = useState(false);
  const update = useMutation({
    mutationFn: (status: string) => send("PATCH", `/insights/${i.id}`, { status }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["insights"] }),
  });
  const a = i.artifact;
  const copy = async () => {
    if (!a) return;
    try {
      await navigator.clipboard.writeText(a.content);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      setOpen(true);
    }
  };
  const download = () => {
    if (!a) return;
    const blob = new Blob([a.content], { type: "text/plain" });
    const url = URL.createObjectURL(blob);
    const el = document.createElement("a");
    el.href = url;
    el.download = (a.path ?? "fix.txt").split("/").pop()!;
    el.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div ref={ref} className="scroll-mt-4">
    <Card>
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-1.5 mb-2">
            <Severity level={i.severity} />
            <span className="chip">{TYPE_LABELS[i.type] ?? i.type}</span>
            {i.project && <span className="chip">{i.project}</span>}
          </div>
          <h3 className="text-sm font-semibold break-words">{i.title}</h3>
          {!compact && <p className="text-sm secondary mt-1.5 max-w-[90ch]">{i.summary}</p>}
        </div>
        {i.status === "done" && i.done_at ? <Realized insight={i} /> : (
          <div className="text-right shrink-0">
            <div className="num text-lg font-semibold">{i.est_usd_month > 0 ? `${money(i.est_usd_month)}/mo` : "–"}</div>
            <div className="text-xs muted">
              {i.est_usd_month > 0 ? "estimated saving" : "saves permission prompts"}
            </div>
            {i.est_tokens > 0 && <div className="text-xs muted num">{tokens(i.est_tokens)} tokens</div>}
          </div>
        )}
      </div>

      {!compact && (
        <div className="flex flex-wrap items-center gap-2 mt-3">
          {a && (
            <button className="btn btn-primary" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
              {open ? "Hide fix" : `Show fix · ${ARTIFACT_LABELS[a.kind] ?? a.kind}`}
            </button>
          )}
          {i.status === "open" ? (
            <>
              <button className="btn" onClick={() => update.mutate("done")}>Mark done</button>
              <button className="btn" onClick={() => update.mutate("dismissed")}>Dismiss</button>
            </>
          ) : (
            <button className="btn" onClick={() => update.mutate("open")}>Reopen</button>
          )}
          <span className="text-xs muted ml-auto">{i.occurrences.toLocaleString()} {i.occurrences === 1 ? "occurrence" : "occurrences"}</span>
        </div>
      )}

      {open && a && (
        <div className="mt-3 space-y-3">
          <div>
            <div className="flex flex-wrap items-center justify-between gap-2 mb-1.5">
              <span className="text-xs secondary num">{a.path ?? "Steps"}</span>
              <span className="flex gap-2">
                <button className="btn" onClick={copy}>{copied ? "Copied" : "Copy"}</button>
                {a.path && <button className="btn" onClick={download}>Download</button>}
              </span>
            </div>
            <pre className="code">{a.content}</pre>
            {a.kind === "settings" && (
              <p className="text-xs muted mt-1.5">Merge these keys into your existing settings file instead of replacing it.</p>
            )}
          </div>
          {i.evidence.length > 0 && (
            <div>
              <div className="text-xs muted mb-1">Seen in</div>
              <ul className="space-y-1">
                {i.evidence.map((e, n) => (
                  <li key={n} className="text-sm">
                    <Link className="hover:underline" to={`/sessions/${e.session_id}${e.turn_id ? `#turn-${e.turn_id}` : ""}`}>
                      {truncate(e.prompt, 110) || e.session_title || e.session_id.slice(0, 8)}
                    </Link>
                    {e.ts && <span className="muted text-xs"> · {dateTime(e.ts)}</span>}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}
    </Card>
    </div>
  );
}
