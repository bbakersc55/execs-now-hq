import { useState } from "react";

import { Banner } from "./ui";

function csrfToken(): string {
  const match = document.cookie.match(/(?:^|;\s*)csrftoken=([^;]+)/);
  return match ? decodeURIComponent(match[1]) : "";
}

/**
 * The signed-out screen (2026-09-30): staff sign in with Google; a client
 * asks for a one-time link by email (C3, C4). The answer is the same whether
 * or not the address has access, so the form never says who is a client.
 */
export function SignedOut({ practice }: { practice: string }) {
  const [email, setEmail] = useState("");
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
        <h3 style={{ marginBottom: ".25rem" }}>Clients</h3>
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
        <h3 style={{ marginBottom: ".25rem" }}>Staff</h3>
        {/* Email first (P2 D1): the address decides which Google sign-in your
            practice uses. A plain GET form: the server answers with a redirect. */}
        <form method="get" action="/accounts/google/start" className="row tight">
          <input type="email" name="email" required aria-label="Your work email"
            placeholder="you@yourpractice.com" autoComplete="email" />
          <button className="btn" type="submit">Sign in with Google</button>
        </form>
      </section>
    </main>
  );
}
