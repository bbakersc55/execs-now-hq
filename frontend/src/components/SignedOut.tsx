import { useState } from "react";

import { Banner } from "./ui";

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

/** The last address a practice sign-in used in this browser (2026-10-27). */
export const LAST_ADDRESS = "enhq_signin_email";

function lastAddress(): string {
  try { return window.localStorage.getItem(LAST_ADDRESS) || ""; } catch { return ""; }
}

function remember(address: string) {
  try { if (address) window.localStorage.setItem(LAST_ADDRESS, address); } catch { /* none */ }
}

/**
 * The signed-out screen (2026-09-30): staff sign in with Google; a client
 * asks for a one-time link by email (C3, C4). The answer is the same whether
 * or not the address has access, so the form never says who is a client.
 *
 * `microsoft` (2026-10-27): the staff of a practice whose mail runs through
 * Microsoft 365 sign in with Microsoft. Both buttons share the one address
 * field; each sends it to its own start, which decides.
 *
 * Straight to the provider (owner, 2026-10-27): either button goes to
 * Google's or Microsoft's own account chooser, no page of ours between. The
 * address is optional: given, it only pre-selects the account there; empty,
 * the chooser does the picking. The last one used here is filled in.
 */
export function SignedOut({ practice, microsoft = false }: {
  practice: string; microsoft?: boolean;
}) {
  const [email, setEmail] = useState("");
  const [workEmail, setWorkEmail] = useState(lastAddress);
  const [state, setState] = useState<"idle" | "sending" | "sent" | "error">("idle");
  const [message, setMessage] = useState("");

  async function send(e: React.FormEvent) {
    e.preventDefault();
    setState("sending");
    const body = new FormData();
    body.append("email", email.trim());
    try {
      const response = await fetch("/auth/magic/request", {
        method: "POST", body, credentials: "same-origin",
        headers: { "X-CSRFToken": csrfToken() },
      });
      const data = await response.json().catch(() => ({}));
      if (response.status === 429) {
        setState("error");
        setMessage("Too many requests. Wait a few minutes and try again.");
        return;
      }
      if (!response.ok) throw new Error(data.detail || `${response.status}`);
      setState("sent");
      setMessage(data.detail || "If that address has access, we've sent a link.");
    } catch {
      setState("error");
      setMessage("That did not go through. Try again in a moment.");
    }
  }

  return (
    <main style={{ padding: "3rem 1rem", maxWidth: "28rem", margin: "0 auto", textAlign: "center" }}>
      <h2>{practice || "Sign in"}</h2>
      <p className="muted">You are not signed in.</p>

      <section style={{ marginTop: "2rem", textAlign: "left" }}>
        <h3 style={{ marginBottom: ".25rem" }}>Client sign-in</h3>
        <p className="small muted" style={{ margin: "0 0 var(--s2)" }}>For clients of a practice</p>
        <p className="small muted" style={{ marginTop: 0 }}>
          Enter the address your portal access was set up with, and we will email
          you a one-time sign-in link.
        </p>
        {state === "sent" ? <Banner kind="ok">{message}</Banner> : (
          <form onSubmit={send} className="row tight">
            <input type="email" required aria-label="Your email address" value={email}
              placeholder="you@company.com" autoComplete="email"
              onChange={(e) => setEmail(e.target.value)} />
            <button className="primary" type="submit" disabled={state === "sending" || !email.trim()}>
              {state === "sending" ? "Sending…" : "Email me a sign-in link"}
            </button>
          </form>
        )}
        {state === "error" && <Banner kind="bad">{message}</Banner>}
      </section>

      <section style={{ marginTop: "2rem", textAlign: "left" }}>
        {/* Was "Staff", which a new practice owner read as his client's staff
            (beta feedback, 2026-10-05). The owner's invitation email names
            this heading: apps/platform/mail.py. */}
        <h3 style={{ marginBottom: ".25rem" }}>Practice sign-in</h3>
        <p className="small muted" style={{ marginTop: 0 }}>For consultants and their team</p>
        {/* The address picks which Google client a practice uses (P2 D1) and
            pre-selects the account; without one, the provider's chooser
            picks. A plain GET form: the server answers with a redirect. */}
        <form method="get" action="/accounts/google/start" className="row tight wrap"
          onSubmit={() => remember(workEmail.trim())}>
          <input type="email" name="email" aria-label="Your work email"
            placeholder="you@yourpractice.com (optional)" autoComplete="email"
            value={workEmail} onChange={(e) => setWorkEmail(e.target.value)} />
          <button className="btn" type="submit">Sign in with Google</button>
          {microsoft && (
            <button className="btn" type="submit" formAction="/accounts/microsoft/start">
              Sign in with Microsoft
            </button>
          )}
        </form>
      </section>
    </main>
  );
}
