import { useEffect, useState, type FormEvent, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import type { AuthStatus } from "./api";

/** Shows the login form when a dashboard password is set and there's no session yet. */
export function AuthGate({ children }: { children: ReactNode }) {
  const qc = useQueryClient();
  useEffect(() => {
    const recheck = () => qc.invalidateQueries({ queryKey: ["auth"] });
    window.addEventListener("wamt:unauthorized", recheck);
    return () => window.removeEventListener("wamt:unauthorized", recheck);
  }, [qc]);
  const q = useAuthStatus();
  if (q.isLoading) return null;
  if (q.data && q.data.required && !q.data.authenticated) return <Login />;
  return <>{children}</>;
}

function Login() {
  const qc = useQueryClient();
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    });
    setBusy(false);
    if (res.ok) {
      await qc.invalidateQueries();
    } else {
      setError("Wrong password");
    }
  };

  return (
    <div className="min-h-screen flex items-center justify-center px-4">
      <form onSubmit={submit} className="card p-6 w-full max-w-sm space-y-4">
        <div>
          <div className="font-semibold tracking-tight">
            <span style={{ color: "var(--accent)" }}>●</span> WhereAreMyTokens
          </div>
          <p className="text-sm secondary mt-1">Enter the dashboard password.</p>
        </div>
        <input
          type="password"
          autoFocus
          autoComplete="current-password"
          aria-label="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-lg px-3 py-2 text-sm"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
        />
        {error && <p className="text-sm" style={{ color: "var(--critical)" }}>{error}</p>}
        <button type="submit" className="btn btn-primary w-full" disabled={busy || !password}>
          {busy ? "Checking…" : "Sign in"}
        </button>
      </form>
    </div>
  );
}

export function useAuthStatus() {
  return useQuery({
    queryKey: ["auth"],
    queryFn: async () => (await fetch("/api/auth/status")).json() as Promise<AuthStatus>,
    refetchInterval: false,
    staleTime: Infinity,
  });
}

export async function logout(invalidate: () => Promise<unknown>) {
  await fetch("/api/auth/logout", { method: "POST" });
  await invalidate();
}

/** Any 401 from the API means the session expired: re-check auth so the login form appears. */
export function onUnauthorized() {
  window.dispatchEvent(new Event("wamt:unauthorized"));
}
