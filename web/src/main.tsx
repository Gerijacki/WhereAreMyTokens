import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useQuery } from "@tanstack/react-query";
import { BrowserRouter, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { get, type IngestStatus } from "./api";
import { AuthGate } from "./auth";
import { dateTime } from "./format";
import Activity from "./pages/Activity";
import Cache from "./pages/Cache";
import Insights from "./pages/Insights";
import Overview from "./pages/Overview";
import Sessions from "./pages/Sessions";
import SessionDetail from "./pages/SessionDetail";
import Tools from "./pages/Tools";
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

function App() {
  return (
    <div className="min-h-screen">
      <header className="border-b" style={{ borderColor: "var(--border)", background: "var(--surface-1)" }}>
        <div className="max-w-[1400px] mx-auto px-4 h-14 flex items-center gap-4">
          <span className="font-semibold tracking-tight whitespace-nowrap">
            <span style={{ color: "var(--accent)" }}>●</span> WhereAreMyTokens
          </span>
          <Nav />
          <div className="ml-auto hidden md:block"><IngestBadge /></div>
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
          <App />
        </AuthGate>
      </BrowserRouter>
    </QueryClientProvider>
  </StrictMode>,
);
