import { useState } from "react";
import { useLocation } from "react-router-dom";

import { api } from "../lib/api";
import { Banner, Field } from "./ui";

/**
 * The Feedback button on every staff screen (P2 §7). What you write, and the
 * screenshot if you add one, go to the platform owner: the one thing that
 * crosses the practice boundary, and only because you sent it.
 */
export function FeedbackButton() {
  const location = useLocation();
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ doing: "", happened: "", expected: "" });
  const [shot, setShot] = useState<File | null>(null);
  const [state, setState] = useState<"idle" | "sending" | "sent">("idle");
  const [problem, setProblem] = useState("");

  async function send() {
    setState("sending");
    setProblem("");
    const body = new FormData();
    Object.entries(form).forEach(([k, v]) => body.append(k, v));
    body.append("page_url", location.pathname + location.search);
    if (shot) body.append("screenshot", shot);
    try {
      await api.post("/api/feedback/", body);
      setState("sent");
      setForm({ doing: "", happened: "", expected: "" });
      setShot(null);
    } catch (e) {
      setState("idle");
      setProblem((e as Error).message);
    }
  }

  if (!open) {
    return (
      <button className="ghost feedback-button" onClick={() => { setOpen(true); setState("idle"); }}>
        Feedback</button>
    );
  }
  const ready = form.doing.trim() && form.happened.trim() && form.expected.trim();
  return (
    <div role="dialog" aria-label="Send feedback" className="feedback-panel">
      <h3 style={{ marginTop: 0 }}>Send feedback</h3>
      {state === "sent" ? (
        <>
          <Banner kind="ok">Thank you. It's on its way.</Banner>
          <button onClick={() => setOpen(false)}>Close</button>
        </>
      ) : (
        <>
          <p className="small muted" style={{ marginTop: 0 }}>
            What you write here, and the screenshot if you add one, go to the platform owner.
            Nothing else about your practice is sent.
          </p>
          <Field label="What were you doing?">
            <textarea aria-label="What were you doing?" rows={2} value={form.doing}
              onChange={(e) => setForm({ ...form, doing: e.target.value })} /></Field>
          <Field label="What happened?">
            <textarea aria-label="What happened?" rows={2} value={form.happened}
              onChange={(e) => setForm({ ...form, happened: e.target.value })} /></Field>
          <Field label="What did you expect?">
            <textarea aria-label="What did you expect?" rows={2} value={form.expected}
              onChange={(e) => setForm({ ...form, expected: e.target.value })} /></Field>
          <Field label="Screenshot (optional)">
            <input type="file" aria-label="Screenshot" accept="image/png,image/jpeg"
              onChange={(e) => setShot(e.target.files?.[0] ?? null)} /></Field>
          {problem && <Banner kind="bad">{problem}</Banner>}
          <div className="row" style={{ gap: "0.5rem" }}>
            <button className="primary" disabled={!ready || state === "sending"} onClick={send}>
              {state === "sending" ? "Sending…" : "Send"}</button>
            <button className="ghost" onClick={() => setOpen(false)}>Cancel</button>
          </div>
        </>
      )}
    </div>
  );
}
