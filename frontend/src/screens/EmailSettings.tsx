import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { GmailStatus, Me, api } from "../lib/api";
import { DevAllowlist } from "./DevAllowlist";
import { SenderSettings } from "./SenderSettings";

const SCOPE_LABELS: Record<string, string> = {
  "https://www.googleapis.com/auth/gmail.send": "Send mail as you",
  "https://www.googleapis.com/auth/gmail.settings.basic": "Read your send-as list",
  "https://www.googleapis.com/auth/gmail.readonly": "Read your mailbox (Tier 2)",
  openid: "Identify the account",
  email: "Identify the account",
};

function scopeLabel(scope: string) {
  return SCOPE_LABELS[scope] ?? scope.replace("https://www.googleapis.com/auth/", "");
}

/** Settings → Email. FF and CF only: a VA never reaches this route (H7). */
export function EmailSettings({ me }: { me: Me }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");

  // The OAuth callback lands here with its outcome in the query string, since
  // it is a browser redirect from Google and cannot return JSON.
  useEffect(() => {
    const connected = params.get("gmail_connected");
    const warning = params.get("gmail_warning");
    const error = params.get("gmail_error");
    if (connected) setNote(`Connected ${connected}.`);
    if (warning) setProblem(warning);
    if (error) setProblem(error);
    if (connected || warning || error) {
      setParams({}, { replace: true });
      qc.invalidateQueries({ queryKey: ["gmail-connection"] });
    }
  }, [params, setParams, qc]);

  const status = useQuery<GmailStatus>({
    queryKey: ["gmail-connection"],
    queryFn: () => api.get<GmailStatus>("/api/gmail-connection/"),
  });

  const start = useMutation({
    mutationFn: () => api.post<{ authorization_url: string }>("/api/gmail-connection/start/"),
    onSuccess: (data) => { window.location.href = data.authorization_url; },
    onError: (e: Error) => setProblem(e.message),
  });

  const verify = useMutation({
    mutationFn: () => api.post<GmailStatus>("/api/gmail-connection/verify/"),
    onSuccess: (data) => {
      qc.setQueryData(["gmail-connection"], data);
      if (data.verify_error) { setProblem(data.verify_error); setNote(""); }
      else { setNote(`${data.alias} is verified. App mail will send as it.`); setProblem(""); }
    },
    onError: (e: Error) => setProblem(e.message),
  });

  const disconnect = useMutation({
    mutationFn: () => api.post<GmailStatus>("/api/gmail-connection/disconnect/"),
    onSuccess: (data) => {
      qc.setQueryData(["gmail-connection"], data);
      setNote("Disconnected. The stored token was deleted with the connection.");
      setProblem("");
    },
    onError: (e: Error) => setProblem(e.message),
  });

  if (status.isLoading) return <p className="muted">Loading…</p>;
  if (status.isError) {
    // Surface the API's own words. For a VA that is the H7 boundary message,
    // and a generic "could not read" would hide the reason they are refused.
    return (
      <>
        <h2>Email settings</h2>
        <Banner kind="bad">{(status.error as Error).message}</Banner>
      </>
    );
  }

  const s = status.data!;
  const busy = start.isPending || verify.isPending || disconnect.isPending;

  return (
    <>
      <h2>Email settings</h2>
      <p className="sub">
        In Beta every app-originated message — magic links, digests, referral touches —
        is sent by a connected Gmail account with <strong>From</strong> set to the
        practice alias. This is your own connection.
      </p>

      {note && <Banner kind="ok">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}

      {!s.oauth_configured && (
        <Banner kind="warn">
          No Google OAuth client is configured, so there is nothing to connect to.
          Set <code>GOOGLE_OAUTH_CLIENT_ID</code> and <code>GOOGLE_OAUTH_CLIENT_SECRET</code>{" "}
          — <code>docs/05_dev_environment.md</code> §5a.
        </Banner>
      )}

      <Card
        title="Your Gmail connection"
        actions={
          s.connected ? (
            <button className="danger" disabled={busy}
              onClick={() => disconnect.mutate()}>
              Disconnect
            </button>
          ) : (
            <button className="primary" disabled={busy || !s.oauth_configured}
              onClick={() => start.mutate()}>
              Connect Gmail
            </button>
          )
        }
      >
        {s.connected ? (
          <>
            <p>
              <Pill kind="ok">connected</Pill> {s.email_address}
              {s.is_sending_connection && (
                <> <Pill kind="ai">practice sending account</Pill></>
              )}
            </p>
            <p className="muted small">Connected {when(s.connected_at)}.</p>
            <p className="muted small">
              Granted: {(s.scopes.length ? s.scopes : ["—"]).map(scopeLabel).join(" · ")}
            </p>
            <p className="muted small">
              Reconnecting replaces the stored token and re-checks the alias. Disconnecting
              deletes the token with the connection.
            </p>
          </>
        ) : (
          <>
            <p><Pill kind="warn">not connected</Pill> No Gmail account is connected for you.</p>
            <p className="muted small">
              Connect asks Google for two permissions and nothing else: send mail as you
              (<code>gmail.send</code>), and read your send-as list
              (<code>gmail.settings.basic</code>). It does not ask to read your mailbox —
              that is Tier 2 and separate.
            </p>
          </>
        )}
      </Card>

      <Card
        title="Practice alias"
        actions={s.connected && (
          <button className="ghost" disabled={busy} onClick={() => verify.mutate()}>
            {s.alias_verified ? "Verify again" : "Verify alias"}
          </button>
        )}
      >
        <p>
          <strong>{s.alias}</strong>{" "}
          {!s.connected ? <Pill>connect to check</Pill>
            : s.alias_verified ? <Pill kind="ok">verified</Pill>
            : s.alias_listed ? <Pill kind="warn">listed, not confirmed</Pill>
            : <Pill kind="bad">missing</Pill>}
        </p>
        {s.alias_verified && (
          <p className="muted small">Verified {when(s.alias_verified_at)}.</p>
        )}
        {s.connected && !s.alias_verified && (
          <Banner kind="warn">
            {s.send_as_error || (
              s.alias_listed
                ? `${s.alias} is on the account but Gmail has not confirmed it. Open the
                   confirmation email Gmail sent, click the link, then Verify alias.`
                : `${s.alias} is not a send-as address on ${s.email_address}. Add it in
                   Gmail → Settings → Accounts and Import → "Send mail as", click the
                   confirmation link, then Verify alias.`
            )}
            {" "}Until it is verified, nothing sends — there is deliberately no fallback
            to your personal address.
          </Banner>
        )}
      </Card>

      <Card title="Send-as addresses Gmail reports">
        {!s.connected ? (
          <Empty>Connect Gmail to see the addresses this account may send as.</Empty>
        ) : s.send_as.length === 0 ? (
          <Empty>
            Gmail returned no send-as addresses{s.send_as_error ? ` — ${s.send_as_error}` : "."}
          </Empty>
        ) : (
          <table>
            <thead>
              <tr><th>Address</th><th>Gmail status</th><th>Role</th></tr>
            </thead>
            <tbody>
              {s.send_as.map((entry) => (
                <tr key={entry.address}>
                  <td>
                    {entry.address}{" "}
                    {entry.is_alias && <Pill kind="ai">practice alias</Pill>}
                  </td>
                  <td>
                    {entry.verification_status === "accepted"
                      ? <Pill kind="ok">accepted</Pill>
                      : <Pill kind="warn">{entry.verification_status}</Pill>}
                  </td>
                  <td className="muted small">
                    {[entry.is_primary && "primary", entry.is_default && "default"]
                      .filter(Boolean).join(", ") || "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      <SenderSettings />

      {/* Rendered only on a localhost build. The API 404s elsewhere, so this
          is two independent locks rather than a hidden button. */}
      {s.is_local_build && <DevAllowlist />}

      <Card title="Transport in use">
        <p><Pill>{s.transport}</Pill> {s.transport_label}</p>
        <p className="muted small">
          Set by <code>APP_MAIL_TRANSPORT</code>. The Outbox stays the single queue and
          the complete send log whichever transport is selected.
        </p>
        {s.practice_sending.ok ? (
          <p className="muted small">
            The practice currently sends through <strong>{s.practice_sending.account}</strong>.
            {me.role === "CF" && s.practice_sending.account !== s.email_address &&
              " That is the founder fractional's connection, not yours."}
          </p>
        ) : (
          <Banner kind="bad">{s.practice_sending.detail}</Banner>
        )}
      </Card>
    </>
  );
}
