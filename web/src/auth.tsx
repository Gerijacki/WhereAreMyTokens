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
  if (q.isLoading) return <div role="status" className="muted text-sm p-6">Loading…</div>;
  if (q.isError)
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div role="alert" className="card p-6 max-w-sm space-y-3">
          <p className="text-sm">Can't reach the server to check the sign-in status.</p>
          <button className="btn btn-primary" onClick={() => q.refetch()}>Try again</button>
        </div>
      </div>
    );
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
    try {
      const res = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password }),
      });
      if (res.ok) await qc.invalidateQueries();
      else if (res.status === 401) setError("Wrong password");
      else if (res.status === 429) setError("Too many attempts. Wait a few minutes and try again.");
      else setError(`The server answered ${res.status}. Try again.`);
    } catch {
      setError("Can't reach the server.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="min-h-screen flex items-center justify-center px-4">
      <form onSubmit={submit} className="card p-6 w-full max-w-sm space-y-4">
        <div>
          <h1 className="font-semibold tracking-tight">
            <span aria-hidden style={{ color: "var(--accent)" }}>●</span> WhereAreMyTokens
          </h1>
          <p className="text-sm secondary mt-1">Enter the dashboard password.</p>
        </div>
        <label htmlFor="login-password" className="block text-sm font-medium">Password</label>
        <input
          id="login-password"
          type="password"
          autoFocus
          autoComplete="current-password"
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "login-error" : undefined}
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className="w-full rounded-lg px-3 py-2 text-sm"
          style={{ background: "var(--surface-2)", border: "1px solid var(--border)", color: "var(--text-primary)" }}
        />
        {error && <p id="login-error" role="alert" className="text-sm" style={{ color: "var(--critical)" }}>{error}</p>}
        <button type="submit" className="btn btn-primary w-full" disabled={busy || !password}>
          {busy ? "Checking…" : "Sign in"}
        </button>
      </form>
    </main>
  );
}

export function useAuthStatus() {
  return useQuery({
    queryKey: ["auth"],
    queryFn: async () => {
      const res = await fetch("/api/auth/status");
      if (!res.ok) throw new Error(`${res.status} ${res.statusText}`); // fail closed: never show the app unchecked
      return (await res.json()) as AuthStatus;
    },
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
