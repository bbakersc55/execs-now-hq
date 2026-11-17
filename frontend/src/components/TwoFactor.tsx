import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { Banner, Card, Field, Pill } from "./ui";
import { ResettablePerson, TwoFactorStart, TwoFactorState, api } from "../lib/api";

/**
 * 2026-11-17: two-factor sign-in by authenticator app (apps/accounts/two_factor.py).
 * The code prompt after sign-in, the card on Profile, the People re-check,
 * the resets card, and the warning before the twelve hours are up.
 */

function CodeBox({ value, onChange, label = "Code from your authenticator app",
                   backup = false }: {
  value: string; onChange: (v: string) => void; label?: string; backup?: boolean;
}) {
  return (
    <Field label={label}>
      <input aria-label={label} value={value} autoComplete="one-time-code"
        inputMode={backup ? "text" : "numeric"} maxLength={backup ? 12 : 6}
        style={{ width: backup ? "10rem" : "7rem", letterSpacing: "0.15em" }}
        onChange={(e) => onChange(backup ? e.target.value : e.target.value.replace(/\D/g, ""))} />
    </Field>
  );
}

/** The whole screen after sign-in until a code is entered. */
export function TwoFactorPrompt({ email }: { email: string }) {
  const qc = useQueryClient();
  const [code, setCode] = useState("");
  const [backup, setBackup] = useState(false);
  const go = useMutation({
    mutationFn: () => api.post("/api/me/two-factor/verify", { code }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["me"] }),
    onError: () => setCode(""),
  });
  return (
    <main style={{ maxWidth: "28rem", margin: "3rem auto", padding: "0 1rem" }}>
      <Card title="Two-factor sign-in">
        <p style={{ marginTop: 0 }}>Signed in as {email}. {backup
          ? "Enter one of your backup codes. Each works once."
          : "Enter the six-digit code your authenticator app shows now."}</p>
        {go.isError && <div role="alert"><Banner kind="bad">{(go.error as Error).message}</Banner></div>}
        <form onSubmit={(e) => { e.preventDefault(); if (code) go.mutate(); }}>
          <CodeBox value={code} onChange={setCode} backup={backup}
            label={backup ? "Backup code" : "Code from your authenticator app"} />
          <div className="row tight">
            <button className="primary" type="submit" disabled={!code || go.isPending}>
              {go.isPending ? "Checking…" : "Continue"}</button>
            <button type="button" className="ghost"
              onClick={() => { setBackup(!backup); setCode(""); }}>
              {backup ? "Use the app instead" : "Use a backup code"}</button>
          </div>
        </form>
        <p className="small muted" style={{ marginBottom: 0 }}>Lost your phone? Ask your
          practice owner (or, for a practice owner, Execs NOW HQ) to reset two-factor
          sign-in. <button type="button" className="link" onClick={() => {
            void api.post("/auth/sign-out", {}).finally(
              () => qc.invalidateQueries({ queryKey: ["me"] }));
          }}>Sign out</button></p>
      </Card>
    </main>
  );
}

/** Profile: turn it on (QR code and typed key, a code, ten backup codes),
 *  replace the backup codes, or turn it off. */
export function TwoFactorCard() {
  const qc = useQueryClient();
  const state = useQuery<TwoFactorState>({
    queryKey: ["two-factor"], queryFn: () => api.get<TwoFactorState>("/api/me/two-factor"),
    retry: false });
  const [started, setStarted] = useState<TwoFactorStart | null>(null);
  const [code, setCode] = useState("");
  const [codes, setCodes] = useState<string[] | null>(null);
  const [error, setError] = useState("");
  const done = (next: TwoFactorState) => {
    qc.setQueryData(["two-factor"], next);
    setCode(""); setError(""); setStarted(null);
    if (next.backup_codes) setCodes(next.backup_codes);
  };
  const fail = (e: Error) => { setError(e.message); setCode(""); };
  const start = useMutation({
    mutationFn: () => api.post<TwoFactorStart>("/api/me/two-factor/start", {}),
    onSuccess: (s) => { setStarted(s); setError(""); setCodes(null); }, onError: fail });
  const confirm = useMutation({
    mutationFn: () => api.post<TwoFactorState>("/api/me/two-factor/confirm", { code }),
    onSuccess: done, onError: fail });
  const replace = useMutation({
    mutationFn: () => api.post<TwoFactorState>("/api/me/two-factor/backup-codes", { code }),
    onSuccess: done, onError: fail });
  const off = useMutation({
    mutationFn: () => api.post<TwoFactorState>("/api/me/two-factor/off", { code }),
    onSuccess: done, onError: fail });
  const s = state.data;
  if (!s) return null;
  return (
    <Card title="Two-factor sign-in">
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
      {s.demo && (
        <p className="small muted" style={{ marginTop: 0 }}>In the demo you can set it up and
          try it; it is never asked for at sign-in or on People screens.</p>
      )}
      {codes && (
        <div role="status" aria-label="Your backup codes">
          <Banner kind="ok">Two-factor sign-in is on. These ten backup codes are shown once:
            keep them somewhere safe. Each works once, if your phone is lost.</Banner>
          <ol className="mono" style={{ columns: 2 }}>
            {codes.map((c) => <li key={c}>{c}</li>)}</ol>
          <button className="small" onClick={() => setCodes(null)}>I have saved them</button>
        </div>
      )}
      {!s.enabled && !started && (
        <>
          <p style={{ marginTop: 0 }}>After you sign in, a code from an authenticator app on
            your phone (Google Authenticator, Microsoft Authenticator, 1Password …) is asked
            for as well. No text messages.{s.required &&
              <> <strong>Required for you: you hold an HR permission.</strong></>}</p>
          <button className="primary" disabled={start.isPending}
            onClick={() => start.mutate()}>Set up two-factor sign-in</button>
        </>
      )}
      {!s.enabled && started && (
        <form aria-label="Set up two-factor sign-in"
          onSubmit={(e) => { e.preventDefault(); if (code) confirm.mutate(); }}>
          <p style={{ marginTop: 0 }}>1. Scan this with your authenticator app, or type the
            key into it.</p>
          <div aria-label="QR code" style={{ width: 180 }}
            dangerouslySetInnerHTML={{ __html: started.qr_svg }} />
          <p className="small">Key: <code aria-label="Key to type">{started.key}</code></p>
          <p>2. Enter the six-digit code it shows.</p>
          <CodeBox value={code} onChange={setCode} />
          <div className="row tight">
            <button className="primary" type="submit" disabled={code.length !== 6
              || confirm.isPending}>Turn it on</button>
            <button type="button" className="ghost" onClick={() => setStarted(null)}>
              Cancel</button>
          </div>
        </form>
      )}
      {s.enabled && !codes && (
        <>
          <p style={{ marginTop: 0 }}><Pill kind="ok">On</Pill> since{" "}
            {s.since ? new Date(s.since).toLocaleDateString() : ""}. {s.backup_codes_left} backup
            code{s.backup_codes_left === 1 ? "" : "s"} left.</p>
          <CodeBox value={code} onChange={setCode}
            label="A code from your app, to change anything here" />
          <div className="row tight">
            <button disabled={code.length !== 6 || replace.isPending}
              onClick={() => replace.mutate()}>New backup codes</button>
            {!s.required && (
              <button className="ghost" disabled={code.length !== 6 || off.isPending}
                onClick={() => off.mutate()}>Turn it off</button>
            )}
          </div>
          {s.required && <p className="small muted">Required while you hold an HR
            permission, so it can't be turned off.</p>}
        </>
      )}
    </Card>
  );
}

/** A People screen's re-check: the code again, after four hours. */
export function CodeAgain({ onDone, message }: { onDone: () => void; message: string }) {
  const [code, setCode] = useState("");
  const go = useMutation({
    mutationFn: () => api.post("/api/me/two-factor/verify", { code }),
    onSuccess: () => { setCode(""); onDone(); },
    onError: () => setCode(""),
  });
  return (
    <Card title="Enter your code again">
      <p style={{ marginTop: 0 }}>{message}</p>
      {go.isError && <div role="alert"><Banner kind="bad">{(go.error as Error).message}</Banner></div>}
      <form onSubmit={(e) => { e.preventDefault(); if (code) go.mutate(); }}>
        <CodeBox value={code} onChange={setCode} />
        <button className="primary" type="submit" disabled={!code || go.isPending}>
          Continue</button>
      </form>
    </Card>
  );
}

/** Who this person may reset two-factor for (with it on): a practice owner
 *  their team and their clients' users; a client owner their own people;
 *  the platform owner practice owners. */
export function TwoFactorResets({ platform = false }: { platform?: boolean }) {
  const qc = useQueryClient();
  const url = platform ? "/api/platform/two-factor/resets" : "/api/two-factor/resets";
  const people = useQuery<{ people: ResettablePerson[] }>({
    queryKey: ["two-factor-resets", platform], queryFn: () => api.get(url), retry: false });
  const [sure, setSure] = useState("");
  const reset = useMutation({
    mutationFn: (membership: string) => api.post(url, { membership }),
    onSuccess: () => { setSure(""); qc.invalidateQueries({ queryKey: ["two-factor-resets"] }); },
  });
  const rows = people.data?.people ?? [];
  if (people.isError || rows.length === 0) return null;
  return (
    <Card title="Two-factor sign-in: lost phones">
      <p className="small muted" style={{ marginTop: 0 }}>Reset it for someone who lost their
        phone: they sign in without a code and set it up again under Profile. Each reset is
        logged, and they are told by email.</p>
      {reset.isError && <Banner kind="bad">{(reset.error as Error).message}</Banner>}
      <ul aria-label="People with two-factor sign-in">
        {rows.map((p) => (
          <li key={p.membership} className="row tight" style={{ flexWrap: "wrap" }}>
            <span>{p.name} <span className="small muted">· {p.role_label}
              {p.company ? ` · ${p.company}` : ""}{p.practice ? ` · ${p.practice}` : ""}</span></span>
            {sure !== p.membership ? (
              <button className="small ghost" aria-label={`Reset two-factor for ${p.name}`}
                onClick={() => setSure(p.membership)}>Reset two-factor</button>
            ) : (
              <button className="small primary" disabled={reset.isPending}
                onClick={() => reset.mutate(p.membership)}>Yes, reset it for {p.name}</button>
            )}
          </li>
        ))}
      </ul>
    </Card>
  );
}

/** Ten minutes before the twelve hours are up, and until then. */
export function SessionEndsBanner({ endsAt }: { endsAt?: string | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  if (!endsAt) return null;
  const ends = new Date(endsAt).getTime();
  const left = ends - now;
  if (left > 10 * 60_000 || left <= 0) return null;
  const at = new Date(ends).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  return (
    <div role="status" aria-label="Signing out soon">
      <Banner kind="warn">You'll be signed out at {at}, 12 hours after you signed in.
        Save what you're writing now: everything saved, drafts included, stays where it is,
        and you sign in again to carry on.</Banner>
    </div>
  );
}
