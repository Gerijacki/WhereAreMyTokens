import { useState, type FormEvent, type ReactNode } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { get, send, type DeviceRow, type ProjectRow, type SettingsData } from "../api";
import { useAuthStatus } from "../auth";
import { Card, ErrorBox, Loading } from "../components/ui";
import { dateTime } from "../format";
import { THEMES, setTheme, useTheme, type Theme } from "../theme";

const THEME_NAMES: Record<Theme, string> = { system: "System", light: "Light", dark: "Dark" };

export default function Settings() {
  const q = useQuery({ queryKey: ["settings"], queryFn: () => get<SettingsData>("/settings") });
  return (
    <div className="space-y-4 max-w-3xl">
      <div>
        <h1 className="text-xl font-semibold">Settings</h1>
        <p className="text-sm secondary">
          Saved on this server for everyone using the dashboard, except the theme, which is per browser.
          Values set with environment variables can't be changed here.
        </p>
      </div>
      <Appearance />
      {q.isLoading && <Loading />}
      {q.error && <ErrorBox error={q.error} />}
      {q.data && <CurrencyAndPlan settings={q.data} />}
      <Security />
      <Devices />
      <Export />
    </div>
  );
}

function Field({ label, hint, children }: { label: string; hint?: ReactNode; children: ReactNode }) {
  return (
    <div className="grid gap-1 sm:grid-cols-[180px_1fr] sm:items-center py-2">
      <span className="text-sm">{label}</span>
      <span className="flex flex-wrap items-center gap-2">
        {children}
        {hint && <span className="text-xs muted">{hint}</span>}
      </span>
    </div>
  );
}

function Appearance() {
  const theme = useTheme();
  return (
    <Card title="Appearance">
      <Field label="Theme" hint="Stored in this browser">
        <span className="seg" role="group" aria-label="Theme">
          {THEMES.map((t) => (
            <button key={t} type="button" aria-pressed={theme === t} onClick={() => setTheme(t)}>{THEME_NAMES[t]}</button>
          ))}
        </span>
      </Field>
    </Card>
  );
}

function CurrencyAndPlan({ settings: s }: { settings: SettingsData }) {
  const qc = useQueryClient();
  const [rate, setRate] = useState(String(s.eur_per_usd));
  const save = useMutation({
    mutationFn: (changes: Partial<SettingsData>) => send<SettingsData>("PATCH", "/settings", changes),
    onSuccess: (next, changes) => {
      // Charts are built once per data change, so a new currency or rate needs a fresh page.
      if ("currency" in changes || "eur_per_usd" in changes) window.location.reload();
      else {
        qc.setQueryData(["settings"], next);
        qc.invalidateQueries({ queryKey: ["plan"] });
      }
    },
  });
  const locked = (f: string) => s.locked.includes(f);
  const lockHint = (f: string) => (locked(f) ? `Set by WAMT_${f.toUpperCase()}` : undefined);
  const saveRate = (e: FormEvent) => {
    e.preventDefault();
    if (Number(rate) > 0) save.mutate({ eur_per_usd: Number(rate) });
  };

  return (
    <Card title="Currency & plan"
      subtitle="Costs are API list prices in US dollars; euros use the rate below. WAMT never looks rates up online.">
      <Field label="Currency" hint={lockHint("currency")}>
        <span className="seg" role="group" aria-label="Currency">
          {s.currencies.map((c) => (
            <button key={c} type="button" aria-pressed={s.currency === c} disabled={locked("currency") || save.isPending}
              onClick={() => s.currency !== c && save.mutate({ currency: c })}>{c}</button>
          ))}
        </span>
      </Field>
      <form onSubmit={saveRate}>
        <Field label="Euros per US dollar" hint={lockHint("eur_per_usd")}>
          <input className="input w-28" type="number" step="0.0001" min="0.0001" aria-label="Euros per US dollar"
            value={rate} onChange={(e) => setRate(e.target.value)} disabled={locked("eur_per_usd")} />
          {!locked("eur_per_usd") && Number(rate) !== s.eur_per_usd && (
            <button className="btn" type="submit" disabled={save.isPending}>Save rate</button>
          )}
        </Field>
      </form>
      <Field label="Your plan" hint={lockHint("plan")}>
        <select className="input" aria-label="Plan" value={s.plan ?? ""} disabled={locked("plan") || save.isPending}
          onChange={(e) => save.mutate({ plan: e.target.value || null })}>
          <option value="">Not set</option>
          {s.plans.map((p) => {
            const price = p.prices[s.currency]?.[s.billing];
            return <option key={p.id} value={p.id}>{p.name}{price !== undefined ? ` · ${s.currency === "EUR" ? "€" : "$"}${price}/mo` : ""}</option>;
          })}
        </select>
      </Field>
      <Field label="Billing" hint={lockHint("billing") ?? "Annual billing compares with the discounted monthly price"}>
        <span className="seg" role="group" aria-label="Billing">
          {(["monthly", "annual"] as const).map((b) => (
            <button key={b} type="button" aria-pressed={s.billing === b} disabled={locked("billing") || save.isPending}
              onClick={() => s.billing !== b && save.mutate({ billing: b })}>{b === "monthly" ? "Monthly" : "Annual"}</button>
          ))}
        </span>
      </Field>
      {save.error && <p className="text-sm" style={{ color: "var(--critical)" }}>{(save.error as Error).message}</p>}
    </Card>
  );
}

function Security() {
  const qc = useQueryClient();
  const auth = useAuthStatus();
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [done, setDone] = useState<string | null>(null);
  const after = (message: string) => {
    setCurrent("");
    setNext("");
    setDone(message);
    qc.invalidateQueries({ queryKey: ["auth"] });
  };
  const change = useMutation({
    mutationFn: () => send("PUT", "/auth/password", { current: current || null, new: next }),
    onSuccess: () => after("Password saved. Other browsers have to sign in again."),
  });
  const remove = useMutation({
    mutationFn: () => send("DELETE", "/auth/password", { current }),
    onSuccess: () => after("Password removed. The dashboard is open to anyone who can reach it."),
  });
  const source = auth.data?.source;
  const error = (change.error ?? remove.error) as Error | null;

  return (
    <Card title="Security" subtitle="Protect the dashboard with a password. Agents and OpenTelemetry use device tokens instead.">
      {auth.data?.proxy_header && (
        <p className="text-sm secondary mb-2">Requests with the <code>{auth.data.proxy_header}</code> header from your reverse proxy are trusted.</p>
      )}
      {source === "env" ? (
        <p className="text-sm">The password is set with <code>WAMT_AUTH_PASSWORD</code>. Change or remove it there.</p>
      ) : (
        <form onSubmit={(e) => { e.preventDefault(); change.mutate(); }} aria-label="Dashboard password">
          <p className="text-sm secondary mb-1">
            {source === "ui" ? "A password is set." : "No password: anyone who can reach this server sees the dashboard."}
          </p>
          {source === "ui" && (
            <Field label="Current password">
              <input className="input" type="password" autoComplete="current-password" aria-label="Current password"
                value={current} onChange={(e) => setCurrent(e.target.value)} required />
            </Field>
          )}
          <Field label={source === "ui" ? "New password" : "Password"} hint="At least 8 characters">
            <input className="input" type="password" autoComplete="new-password" minLength={8}
              aria-label={source === "ui" ? "New password" : "Password"} value={next} onChange={(e) => setNext(e.target.value)} required />
          </Field>
          <div className="flex flex-wrap gap-2 mt-2">
            <button className="btn btn-primary" type="submit" disabled={change.isPending}>
              {source === "ui" ? "Change password" : "Set password"}
            </button>
            {source === "ui" && (
              <button className="btn" type="button" disabled={remove.isPending || !current} onClick={() => remove.mutate()}>
                Remove password
              </button>
            )}
          </div>
        </form>
      )}
      {done && <p className="text-sm mt-2" style={{ color: "var(--good)" }} role="status">{done}</p>}
      {error && <p className="text-sm mt-2" style={{ color: "var(--critical)" }} role="alert">{error.message}</p>}
    </Card>
  );
}

function Devices() {
  const qc = useQueryClient();
  const q = useQuery({ queryKey: ["devices"], queryFn: () => get<DeviceRow[]>("/devices") });
  const [name, setName] = useState("");
  const [token, setToken] = useState<{ name: string; token: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const add = useMutation({
    mutationFn: () => send<DeviceRow & { token: string }>("POST", "/devices", { name }),
    onSuccess: (d) => {
      setToken({ name: d.name, token: d.token });
      setName("");
      qc.invalidateQueries({ queryKey: ["devices"] });
    },
  });
  const revoke = useMutation({
    mutationFn: (n: string) => send("DELETE", `/devices/${encodeURIComponent(n)}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["devices"] }),
  });
  const copy = async () => {
    if (!token) return;
    try {
      await navigator.clipboard.writeText(token.token);
      setCopied(true);
    } catch {
      setCopied(false);
    }
  };
  const server = window.location.origin;

  return (
    <Card title="Devices" subtitle="Other machines push their usage here with `wamt agent` and a device token.">
      <form className="flex flex-wrap gap-2 mb-3" aria-label="New device"
        onSubmit={(e) => { e.preventDefault(); setCopied(false); add.mutate(); }}>
        <input className="input" placeholder="work-laptop" aria-label="Device name" pattern="[\w.\-]+"
          title="Letters, digits, dots, dashes and underscores" value={name} onChange={(e) => setName(e.target.value)} required />
        <button className="btn btn-primary" type="submit" disabled={add.isPending}>Add device</button>
        {add.error && <span className="text-sm" style={{ color: "var(--critical)" }}>{(add.error as Error).message}</span>}
      </form>
      {token && (
        <div className="mb-3" data-testid="device-token">
          <p className="text-sm mb-1">
            Token for <b>{token.name}</b>. Copy it now: it won't be shown again.
          </p>
          <div className="flex gap-2 items-start">
            <pre className="code flex-1">{`wamt agent --server ${server} --token ${token.token}`}</pre>
            <button className="btn" onClick={copy}>{copied ? "Copied" : "Copy token"}</button>
          </div>
        </div>
      )}
      {q.data && q.data.length > 0 ? (
        <div className="overflow-x-auto">
          <table className="data-table">
            <thead><tr><th>Device</th><th>Added</th><th>Last push</th><th>Status</th><th /></tr></thead>
            <tbody>
              {q.data.map((d) => (
                <tr key={d.name}>
                  <td>{d.name}</td>
                  <td className="secondary">{dateTime(d.created_at)}</td>
                  <td className="secondary">{d.last_seen_at ? dateTime(d.last_seen_at) : "never"}</td>
                  <td>{d.revoked ? <span className="muted">revoked</span> : "active"}</td>
                  <td className="r">
                    {!d.revoked && (
                      <button className="btn" aria-label={`Revoke ${d.name}`} onClick={() => revoke.mutate(d.name)}>Revoke</button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="text-sm muted">No devices yet. This server always reads its own transcripts.</p>
      )}
    </Card>
  );
}

const DATASETS = [
  { id: "sessions", label: "Sessions", hint: "one row per session" },
  { id: "prompts", label: "Prompts", hint: "one row per prompt, with its text if stored" },
  { id: "daily", label: "Daily costs", hint: "per day, project and model" },
];
const RANGES = [{ days: 7, label: "Last 7 days" }, { days: 30, label: "Last 30 days" }, { days: 90, label: "Last 90 days" }, { days: 0, label: "All time" }];

function Export() {
  const projects = useQuery({ queryKey: ["projects", 0], queryFn: () => get<ProjectRow[]>("/projects", { days: 0 }) });
  const [dataset, setDataset] = useState("sessions");
  const [fmt, setFmt] = useState("csv");
  const [days, setDays] = useState(30);
  const [project, setProject] = useState("");
  const qs = new URLSearchParams({ days: String(days), ...(project ? { project_id: project } : {}) });
  const href = `/api/export/${dataset}.${fmt}?${qs}`;
  return (
    <Card title="Export" subtitle="API-equivalent costs in USD, plus a column in euros when that's your currency.">
      <Field label="Data" hint={DATASETS.find((d) => d.id === dataset)?.hint}>
        <select className="input" aria-label="Export data" value={dataset} onChange={(e) => setDataset(e.target.value)}>
          {DATASETS.map((d) => <option key={d.id} value={d.id}>{d.label}</option>)}
        </select>
      </Field>
      <Field label="Range">
        <select className="input" aria-label="Export range" value={days} onChange={(e) => setDays(Number(e.target.value))}>
          {RANGES.map((r) => <option key={r.days} value={r.days}>{r.label}</option>)}
        </select>
        <select className="input" aria-label="Export project" value={project} onChange={(e) => setProject(e.target.value)}>
          <option value="">All projects</option>
          {projects.data?.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select>
      </Field>
      <Field label="Format">
        <span className="seg" role="group" aria-label="Export format">
          {["csv", "json"].map((f) => (
            <button key={f} type="button" aria-pressed={fmt === f} onClick={() => setFmt(f)}>{f.toUpperCase()}</button>
          ))}
        </span>
      </Field>
      <a className="btn btn-primary inline-block mt-2" href={href} download>Download</a>
    </Card>
  );
}
