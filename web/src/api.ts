import { onUnauthorized } from "./auth";

export interface Usage {
  input_tokens: number;
  output_tokens: number;
  cache_write_5m: number;
  cache_write_1h: number;
  cache_write: number;
  cache_read: number;
  total_tokens: number;
  cache_hit_ratio: number | null;
  cost_usd: number;
  api_calls: number;
  unpriced_calls: number;
}

export interface Overview {
  days: number;
  totals: Usage & { sessions: number; prompts: number };
  cost_by_kind: Record<"input" | "output" | "cache_write" | "cache_read", number>;
  by_model: (Usage & { model: string })[];
  daily: (Usage & { day: string })[];
  daily_by_model: { day: string; model: string; cost_usd: number }[];
  by_thread: (Usage & { thread: "main" | "subagents" })[];
}

export interface ProjectRow extends Usage {
  id: number;
  name: string;
  path: string | null;
  sessions: number;
}

export interface SessionRow extends Usage {
  id: string;
  title: string | null;
  project_id: number;
  project: string | null;
  git_branch: string | null;
  entrypoint: string | null;
  version: string | null;
  started_at: string | null;
  ended_at: string | null;
}

export interface TurnRow extends Usage {
  id: string;
  ts: string;
  prompt: string | null;
  permission_mode: string | null;
  category: string | null;
  category_source: "rules" | "manual" | null;
  category_confidence: number | null;
  category_scores: Record<string, number>;
  tools: Record<string, number>;
}

export interface SessionEventRow {
  ts: string;
  kind: "compact" | "command" | "cache_rebuild";
  cause: string | null;
  tokens: number;
  wasted_usd: number;
}

export interface SessionDetail extends SessionRow {
  models: string[];
  turns: TurnRow[];
  events: SessionEventRow[];
}

export interface TopTurn extends Usage {
  id: string;
  ts: string;
  prompt: string | null;
  category: string | null;
  session_id: string;
  session_title: string | null;
  project: string | null;
}

export interface IngestStatus {
  running: boolean;
  files_seen: number;
  files_changed: number;
  lines_total: number;
  last_scan_at: string | null;
  last_scan_seconds: number;
  last_error: string | null;
}

export async function get<T>(path: string, params: Record<string, string | number | undefined> = {}): Promise<T> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v !== undefined && v !== "") qs.set(k, String(v));
  const res = await fetch(`/api${path}${qs.size ? `?${qs}` : ""}`);
  if (res.status === 401) onUnauthorized();
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export interface CategoriesData {
  categories: string[];
  by_category: (Usage & { category: string; prompts: number; cost_per_prompt: number })[];
  daily: { day: string; category: string; cost_usd: number }[];
}

export interface ToolsData {
  by_tool: { name: string; calls: number; errors: number; error_rate: number; result_tokens: number;
    avg_result_tokens: number; sessions: number }[];
  commands: { signature: string; calls: number; errors: number; prompts: number; avg_result_tokens: number }[];
  files: { path: string; reads: number; sessions: number; avg_result_tokens: number }[];
  biggest_results: { id: string; name: string; target: string | null; result_tokens: number; session_id: string;
    turn_id: string | null; ts: string }[];
}

export interface CacheData {
  totals: { cache_read: number; cache_write: number; input_tokens: number; saved_usd: number; read_usd: number;
    write_usd: number; hit_ratio: number | null };
  by_cause: { cause: string; label: string; rebuilds: number; tokens: number; wasted_usd: number }[];
  sessions: { session_id: string; title: string | null; rebuilds: number; tokens: number; wasted_usd: number }[];
  events: { session_id: string; title: string | null; ts: string; cause: string; model: string; tokens: number;
    wasted_usd: number; gap_seconds: number | null }[];
  contexts: { session_id: string; title: string | null; avg_context: number; max_context: number; calls: number }[];
}

export interface Block {
  start: string;
  end: string;
  cost_usd: number;
  tokens: number;
  cache_read: number;
  output_tokens: number;
  calls: number;
  active_minutes: number;
}

export interface LimitsData {
  block_hours: number;
  timezone: string;
  current: { start: string; end: string; cost_usd: number; tokens: number; calls: number; burn_usd_per_hour: number;
    projected_cost_usd: number; minutes_left: number } | null;
  peak_block_cost_usd: number;
  median_block_cost_usd: number;
  blocks: Block[];
  heatmap: number[][];
  weekly: { week: string; cost_usd: number }[];
}

export interface Insight {
  id: string;
  type: string;
  title: string;
  summary: string;
  severity: "high" | "medium" | "low";
  project_id: number | null;
  project: string | null;
  occurrences: number;
  est_tokens: number;
  est_usd: number;
  est_usd_month: number;
  evidence: { session_id: string; turn_id: string | null; session_title: string | null; prompt: string | null;
    ts: string | null }[];
  artifact: { kind: string; path: string | null; content: string } | null;
  status: "open" | "dismissed" | "done";
  stale: boolean;
  done_at: string | null;
  baseline_usd_month: number | null;
  residual_usd_month: number | null;
  realized_usd_month: number | null;
  measured_at: string | null;
}

export interface InsightsData {
  refreshed_at: string | null;
  summary: { open: number; done: number; dismissed: number; open_usd_month: number; realized_usd_month: number;
    measuring: number };
  items: Insight[];
}

export interface PlanData {
  current_plan: string | null;
  billing: "monthly" | "annual";
  monthly_usd: number;
  trailing_30d_usd: number;
  history_days: number;
  plans: { id: string; name: string; price: number; price_currency: string; usd_month: number;
    value_multiple: number | null; api_cheaper: boolean }[];
  months: { month: string; cost_usd: number; partial: boolean; projected_usd: number | null }[];
}

export type BudgetPeriod = "day" | "week" | "month";

export interface BudgetRow {
  id: number;
  period: BudgetPeriod;
  limit_usd: number;
  project_id: number | null;
  project: string | null;
  period_start: string;
  period_end: string;
  spent_usd: number;
  ratio: number | null;
  projected_usd: number | null;
  state: "ok" | "warning" | "over";
}

export interface SettingsData {
  currency: "EUR" | "USD";
  eur_per_usd: number;
  plan: string | null;
  billing: "monthly" | "annual";
  locked: string[];
  currencies: ("EUR" | "USD")[];
  plans: { id: string; name: string; prices: Record<string, Record<string, number>> }[];
}

export interface AuthStatus {
  required: boolean;
  authenticated: boolean;
  source: "env" | "ui" | "none";
  proxy_header: string | null;
}

export interface DeviceRow {
  name: string;
  created_at: string;
  last_seen_at: string | null;
  revoked: boolean;
}

export async function send<T>(method: "PATCH" | "POST" | "PUT" | "DELETE", path: string, body?: unknown): Promise<T> {
  const res = await fetch(`/api${path}`, {
    method,
    headers: body === undefined ? undefined : { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (res.status === 401 && !path.startsWith("/auth/")) onUnauthorized();
  if (!res.ok) {
    const detail = await res.json().then((b) => b?.detail, () => null);
    throw new Error(typeof detail === "string" ? detail : `${res.status} ${res.statusText}`);
  }
  return res.json() as Promise<T>;
}
