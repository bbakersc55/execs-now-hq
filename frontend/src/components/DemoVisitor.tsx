import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ReactNode, useEffect, useState } from "react";

import { api, DemoVisitorInfo, Me } from "../lib/api";
import { Modal, PageHead } from "./shell";
import { Banner, Card } from "./ui";

/**
 * A demo visitor's own copy of the demo practice (Melissa's feedback W1,
 * decisions 2026-10-17): its setup page, its banner, "Your demo" in
 * Settings with "Reset my demo", and the stop on its AI that every AI control
 * shows instead of itself. apps/tenancy/demo/visitors.py is the server's side.
 */

/** "October 17, 2026", in the reader's own time. */
export function day(iso: string) {
  return new Date(iso).toLocaleDateString(undefined,
    { month: "long", day: "numeric", year: "numeric" });
}

/** The page a copy shows while it is being set up, or when its setup did not
 *  finish. It asks again every few seconds and opens the copy when ready. */
export function DemoSettingUp({ me }: { me: Me }) {
  const qc = useQueryClient();
  const failed = me.demo_visitor?.state === "failed";
  useEffect(() => {
    if (failed) return;
    const tick = window.setInterval(
      () => qc.invalidateQueries({ queryKey: ["me"] }), 5000);
    return () => window.clearInterval(tick);
  }, [qc, failed]);
  return (
    <main className="demo-setting-up" style={{ maxWidth: "36rem", margin: "4rem auto",
                                               padding: "0 1rem" }}>
      <Card title={failed ? "Your demo's setup did not finish"
                          : "Your demo is being set up"}>
        {failed ? (
          <p>Ask whoever invited you to reset it, and it will be set up again. Nothing you
            did is lost: there was nothing in it yet.</p>
        ) : (
          <>
            <p role="status">We are building your own copy of the demo practice: its clients,
              their goals and tasks, strategy sessions, invoices and two years of books, all
              dated from today. It takes a few minutes.</p>
            <p className="muted small">This page opens it by itself when it is ready. You can
              leave it open, or come back later.</p>
          </>
        )}
      </Card>
    </main>
  );
}

/** Staff's banner in a copy: whose it is, until when, and where its mail goes;
 *  once it has ended, that it is read-only. */
export function DemoVisitorBanner({ me }: { me: Me }) {
  const demo = me.demo_visitor;
  if (!demo) return null;
  if (demo.read_only) {
    return (
      <Banner kind="warn">
        <span><strong>This demo has ended.</strong> You can look around until{" "}
          {day(demo.deletes_on)}; then it is deleted. Nothing in it can be changed.</span>
      </Banner>
    );
  }
  return (
    <Banner kind="warn">
      <span><strong>Your own demo</strong>, a fictional practice, yours until{" "}
        {day(demo.expires_at)}. Everything it sends comes to {me.acting?.real_email
          ?? me.email} and nobody else. Settings → Your demo starts it fresh.</span>
    </Banner>
  );
}

/** The copy's `demo_visitor`, from the same `/api/me` the app already holds. */
export function useDemoVisitor(): DemoVisitorInfo | null {
  // The app has already asked; this only reads its answer, and follows it.
  const { data } = useQuery<Me>({ queryKey: ["me"], queryFn: () => api.get<Me>("/api/me"),
                                  enabled: false });
  return data?.demo_visitor ?? null;
}

/** Why AI is off here, or "". */
export function useAiStop(): string {
  return useDemoVisitor()?.ai_stop ?? "";
}

/**
 * Wraps an AI control. When the copy's AI is stopped, the control is not
 * offered: the reason is, in its place (decision 4).
 */
export function AiGate({ children }: { children: ReactNode }) {
  const stop = useAiStop();
  if (!stop) return <>{children}</>;
  return <span className="small muted ai-stopped" role="status">{stop}</span>;
}

/** What "Reset my demo" takes away, said before it does. */
const WHAT_GOES = [
  "the contacts, companies, prospects and referral partners, and the pipeline",
  "the clients, their goals, projects and tasks, comments and digests",
  "notes, strategy sessions and the meeting queue",
  "every email, invoice and payment, and the books and personal finances",
  "anything you added, changed or deleted",
];

/** Settings → Your demo: when it ends, its AI allowance, and "Reset my demo". */
export function DemoSettings({ me }: { me: Me }) {
  const qc = useQueryClient();
  const demo = me.demo_visitor;
  const [asking, setAsking] = useState(false);
  const [problem, setProblem] = useState("");
  const reset = useMutation({
    mutationFn: () => api.post<{ demo_visitor: DemoVisitorInfo }>("/api/demo/reset"),
    onSuccess: () => { setAsking(false); qc.invalidateQueries({ queryKey: ["me"] }); },
    onError: (e: Error) => { setAsking(false); setProblem(e.message); },
  });
  if (!demo) return null;
  return (
    <>
      <PageHead title="Your demo"
        sub={<>Your own copy of the demo practice. It is yours until {day(demo.expires_at)}.</>} />
      {problem && <Banner kind="bad">{problem}</Banner>}
      <Card title="AI">
        <p style={{ marginTop: 0 }}>
          Your demo's AI runs on our key, up to ${demo.ai_per_day_usd} a day and
          ${demo.ai_in_all_usd} in all. Spent today: ${demo.ai_spent_today_usd}; in all:
          ${demo.ai_spent_total_usd}.
        </p>
        {demo.ai_stop && <Banner kind="warn">{demo.ai_stop}</Banner>}
      </Card>
      <Card title="Reset my demo">
        <p style={{ marginTop: 0 }}>Empties your demo and sets it up again, as it was when
          you first signed in, dated from today.</p>
        <button className="danger" disabled={demo.read_only || reset.isPending}
          onClick={() => setAsking(true)}>Reset my demo</button>
        {demo.read_only && <p className="small muted">Your demo has ended, so it cannot be
          reset.</p>}
      </Card>
      {asking && (
        <Modal title="Reset your demo?" label="Reset your demo" onClose={() => setAsking(false)}>
          <p>This empties your demo and sets it up again as of today. It takes a few minutes,
            and cannot be undone.</p>
          <p style={{ marginBottom: ".25rem" }}><strong>What goes:</strong></p>
          <ul style={{ marginTop: 0 }}>{WHAT_GOES.map((line) => <li key={line}>{line}</li>)}</ul>
          <p><strong>What stays:</strong> your sign-in, and the day your demo ends
            ({day(demo.expires_at)}). The AI you have used still counts.</p>
          <div className="row tight">
            <button className="danger" disabled={reset.isPending}
              onClick={() => reset.mutate()}>
              {reset.isPending ? "Resetting…" : "Reset my demo"}</button>
            <button className="ghost" onClick={() => setAsking(false)}>Cancel</button>
          </div>
        </Modal>
      )}
    </>
  );
}

/** Settings → Email in a copy: there is nothing to connect (decision 2). */
export function DemoEmailSettings({ me }: { me: Me }) {
  return (
    <>
      <PageHead title="Email" />
      <Card title="Gmail and Drive">
        <p style={{ marginTop: 0 }}>This is your own copy of the demo, so it connects no Gmail
          or Drive. Everything it sends (digests, invoices, sign-in links) comes to{" "}
          {me.acting?.real_email ?? me.email}, through the demo's own connection, from the
          demo's address. Nobody in it is real, and nobody else receives anything.</p>
      </Card>
    </>
  );
}
