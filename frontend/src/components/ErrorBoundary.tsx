import { Component, ErrorInfo, ReactNode } from "react";

interface Props { children: ReactNode; onReset?: () => void }
interface State { error: Error | null; info: string }

/**
 * A render exception anywhere below this renders the error, not a blank page.
 *
 * React unmounts the whole tree when a component throws during render, so a
 * single bad field produced a white screen with the reason visible only in the
 * browser console — which made the one useful piece of evidence the hardest
 * thing to get hold of. This keeps the app frame and shows what threw.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null, info: "" };

  static getDerivedStateFromError(error: Error): Partial<State> {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Still logged, so the console trace is there for anyone who wants it.
    console.error("Render failed:", error, info.componentStack);
    this.setState({ info: info.componentStack ?? "" });
  }

  render() {
    const { error, info } = this.state;
    if (!error) return this.props.children;
    return (
      <div className="card" role="alert">
        <h3 style={{ marginTop: 0 }}>This screen failed to render.</h3>
        <p className="muted small">
          The rest of the app still works — use the sidebar. Copy the message below
          when reporting it; that is the part that says what actually went wrong.
        </p>
        <pre className="mono small" style={{ whiteSpace: "pre-wrap", overflowX: "auto" }}>
          {error.message}
        </pre>
        {info && (
          <details>
            <summary className="small">Component stack</summary>
            <pre className="mono small" style={{ whiteSpace: "pre-wrap", overflowX: "auto" }}>
              {info.trim()}
            </pre>
          </details>
        )}
        <button onClick={() => {
          this.setState({ error: null, info: "" });
          this.props.onReset?.();
        }}>
          Try again
        </button>
      </div>
    );
  }
}
