import type { ReactNode } from "react";

export function Card({ title, subtitle, action, children, className = "" }: {
  title?: string;
  subtitle?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`card p-4 min-w-0 ${className}`}>
      {(title || action) && (
        <header className="flex items-start justify-between gap-3 mb-3">
          <div>
            {title && <h2 className="text-sm font-semibold">{title}</h2>}
            {subtitle && <p className="text-xs muted mt-0.5">{subtitle}</p>}
          </div>
          {action}
        </header>
      )}
      {children}
    </section>
  );
}

export function Stat({ label, value, hint }: { label: string; value: string; hint?: ReactNode }) {
  return (
    <div className="card p-4 min-w-0">
      <div className="text-xs muted">{label}</div>
      <div className="num text-2xl font-semibold mt-1 truncate">{value}</div>
      {hint && <div className="text-xs secondary mt-1">{hint}</div>}
    </div>
  );
}

export function Loading() {
  return <div className="muted text-sm p-6">Loading…</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  return (
    <div className="card p-4 text-sm" style={{ color: "var(--critical)" }}>
      Failed to load: {error instanceof Error ? error.message : String(error)}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="muted text-sm p-6 text-center">{children}</div>;
}
