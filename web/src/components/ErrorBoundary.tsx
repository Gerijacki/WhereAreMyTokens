import { Component, type ErrorInfo, type ReactNode } from "react";

/** Keeps a render error from blanking the whole page; offers a reload instead. */
export class ErrorBoundary extends Component<{ children: ReactNode }, { error: Error | null }> {
  state = { error: null as Error | null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div className="min-h-screen flex items-center justify-center px-4">
        <div role="alert" className="card p-6 max-w-md space-y-3">
          <h1 className="text-xl font-semibold">Something went wrong</h1>
          <p className="text-sm secondary">The dashboard hit an unexpected error. Reloading usually fixes it.</p>
          <p className="text-xs muted num break-words">{this.state.error.message}</p>
          <button className="btn btn-primary" onClick={() => window.location.reload()}>Reload</button>
        </div>
      </div>
    );
  }
}
