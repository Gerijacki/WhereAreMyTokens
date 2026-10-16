import { StrictMode, type ReactNode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery, useQueryClient } from "@tanstack/react-query";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { get, type IngestStatus, type SettingsData } from "./api";
import { AuthGate, logout, useAuthStatus } from "./auth";
import { dateTime, setCurrency } from "./format";
import Activity from "./pages/Activity";
import Cache from "./pages/Cache";
import Insights from "./pages/Insights";
import Overview from "./pages/Overview";
import Sessions from "./pages/Sessions";
import SessionDetail from "./pages/SessionDetail";
import Settings from "./pages/Settings";
import Tools from "./pages/Tools";
import { THEMES, setTheme, useTheme, type Theme } from "./theme";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { refetchInterval: 30_000, staleTime: 10_000, refetchOnWindowFocus: false } },
});

const PAGES = [
  { to: "/", label: "Overview" },
  { to: "/activity", label: "Activity" },
  { to: "/insights", label: "Insights" },
  { to: "/tools", label: "Tools" },
  { to: "/cache", label: "Cache" },
  { to: "/sessions", label: "Sessions" },
  { to: "/settings", label: "Settings" },
];

function Nav() {
  const { search } = useLocation();
  // Keep range/project filters when switching pages.
  const keep = new URLSearchParams(search);
  keep.delete("sort");
  keep.delete("status");
  const qs = keep.size ? `?${keep}` : "";
  const link = ({ isActive }: { isActive: boolean }) =>
    `px-3 py-1.5 rounded-lg text-sm whitespace-nowrap ${isActive ? "font-medium" : "secondary"}`;
  const style = ({ isActive }: { isActive: boolean }) => (isActive ? { background: "var(--surface-2)" } : undefined);
  return (
    <nav className="flex gap-1 overflow-x-auto">
      {PAGES.map((p) => (
        <NavLink key={p.to} to={`${p.to}${qs}`} end={p.to === "/"} className={link} style={style}>
          {p.label}
        </NavLink>
      ))}
    </nav>
  );
}

function IngestBadge() {
  const q = useQuery({ queryKey: ["ingest"], queryFn: () => get<IngestStatus>("/ingest/status"), refetchInterval: 10_000 });
  if (!q.data) return null;
  const s = q.data;
  return (
    <span className="text-xs muted inline-flex items-center gap-1.5" title={s.last_error ?? undefined}>
      <span aria-hidden className="inline-block w-2 h-2 rounded-full"
        style={{ background: s.last_error ? "var(--critical)" : s.running ? "var(--series-3)" : "var(--text-muted)" }} />
      {s.running ? `Live · ${s.files_seen} transcripts · scanned ${dateTime(s.last_scan_at)}` : "Collector off"}
    </span>
  );
}

const THEME_LABELS: Record<Theme, string> = { system: "System theme", light: "Light theme", dark: "Dark theme" };

function ThemeIcon({ theme }: { theme: Theme }) {
  const common = { width: 16, height: 16, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 2,
    strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  if (theme === "light") {
    return (
      <svg {...common}>
        <circle cx="12" cy="12" r="4" />
        <path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4" />
      </svg>
    );
  }
  if (theme === "dark") return <svg {...common}><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8z" /></svg>;
  return (
    <svg {...common}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 3a9 9 0 0 1 0 18z" fill="currentColor" />
    </svg>
  );
}

/** Cycles System → Light → Dark. Settings has the same choice as a labelled control. */
function ThemeToggle() {
  const theme = useTheme();
  const next = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
  return (
    <button className="btn px-2 py-1.5 inline-flex" aria-label={`${THEME_LABELS[theme]}. Switch to ${THEME_LABELS[next].toLowerCase()}`}
      title={THEME_LABELS[theme]} onClick={() => setTheme(next)}>
      <ThemeIcon theme={theme} />
    </button>
  );
}

function LogoutButton() {
  const qc = useQueryClient();
  const auth = useAuthStatus();
  if (!auth.data?.required || auth.data.source === "none") return null;
  return <button className="btn" onClick={() => logout(() => qc.invalidateQueries())}>Log out</button>;
}

/** Loads the display preferences (currency) before anything formats an amount. */
function SettingsGate({ children }: { children: ReactNode }) {
  const q = useQuery({ queryKey: ["settings"], queryFn: () => get<SettingsData>("/settings"), staleTime: Infinity,
    refetchInterval: false });
  if (q.data) setCurrency(q.data.currency, q.data.eur_per_usd);
  else if (q.isLoading) return null;
  return <>{children}</>;
}

function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
        <div className="max-w-[1400px] mx-auto px-4 h-14 flex items-center gap-4">
          <span className="font-semibold tracking-tight whitespace-nowrap">
            <span style={{ color: "var(--accent)" }}>●</span> WhereAreMyTokens
          </span>
          <Nav />
          <div className="ml-auto flex items-center gap-3">
            <span className="hidden md:inline"><IngestBadge /></span>
            <ThemeToggle />
            <LogoutButton />
          </div>
        </div>
      </header>
      <main className="max-w-[1400px] mx-auto px-4 py-6">
        <Routes>
          <Route path="/" element={<Overview />} />
          <Route path="/activity" element={<Activity />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/tools" element={<Tools />} />
          <Route path="/cache" element={<Cache />} />
          <Route path="/sessions" element={<Sessions />} />
          <Route path="/sessions/:id" element={<SessionDetail />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthGate>
          <SettingsGate>
            <App />
          </SettingsGate>
        </AuthGate>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
