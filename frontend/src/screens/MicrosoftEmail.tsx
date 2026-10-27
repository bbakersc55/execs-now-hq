import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { PageHead } from "../components/shell";
import { Banner, Card, Field, Pill, when } from "../components/ui";
import { MailProvider, Me, MicrosoftStatus, api } from "../lib/api";
import { DevAllowlist } from "./DevAllowlist";
import { SenderSettings } from "./SenderSettings";

const SCOPE_LABELS: Record<string, string> = {
  "mail.send": "Send mail as you",
  "mail.readbasic": "See who sent a message (for the practice address check)",
  "mail.read": "Read your mailbox",
  "user.read": "Identify the account",
};

function scopeLabel(scope: string) {
  return SCOPE_LABELS[scope.toLowerCase()] ?? null;
}

/**
 * "Mail goes through": the practice's one transport, Gmail or Microsoft 365
 * (docs/m365_transport.md, D6). The practice owner switches it; everyone
 * else on this screen sees which.
 */
export function MailProviderCard({ provider }: { provider: MailProvider }) {
  const qc = useQueryClient();
  const [wanted, setWanted] = useState(provider.provider);
  const [problem, setProblem] = useState("");
  useEffect(() => setWanted(provider.provider), [provider.provider]);

  const switchTo = useMutation({
    mutationFn: (value: string) =>
      api.post<MailProvider>("/api/mail-provider/switch/", { provider: value }),
    onSuccess: (next) => {
      qc.setQueryData(["mail-provider"], next);
      qc.invalidateQueries({ queryKey: ["gmail-connection"] });
      qc.invalidateQueries({ queryKey: ["microsoft-connection"] });
      setProblem("");
    },
    onError: (e: Error) => setProblem(e.message),
  });

  const other = provider.choices.find((c) => c.value === wanted);
  const changing = wanted !== provider.provider;

  return (
    <Card title="Mail goes through">
      <p>
        <strong>{provider.label}</strong>{" "}
        <Pill kind="ai">the practice's transport</Pill>
      </p>
      {provider.refusal && <Banner kind="info">{provider.refusal}</Banner>}
      {provider.can_switch ? (
        <>
          <fieldset className="questions">
            <legend className="small muted">
              One at a time. Every message the app sends for the practice, and every reply
              it collects, goes through this one.
            </legend>
            <div className="row tight wrap">
              {provider.choices.map((choice) => (
                <label key={choice.value} className="choice">
                  <input type="radio" name="mail-provider" checked={wanted === choice.value}
                    onChange={() => setWanted(choice.value)} />
                  <span>{choice.label}</span>
                </label>
              ))}
            </div>
          </fieldset>
          {changing && (
            <Banner kind="warn">
              Switching to {other?.label}: nothing sends until a {other?.label} account is
              connected below and the practice address passes its check. Replies are
              collected only for conversations started through {other?.label} from then on.
              Nothing is deleted; switching back needs no reconnect.
            </Banner>
          )}
          {problem && <Banner kind="bad">{problem}</Banner>}
          {changing && (
            <div className="row tight wrap">
              <button className="primary" disabled={switchTo.isPending}
                onClick={() => switchTo.mutate(wanted)}>
                {switchTo.isPending ? "Switching…" : `Switch to ${other?.label}`}
              </button>
              <button disabled={switchTo.isPending}
                onClick={() => setWanted(provider.provider)}>Cancel</button>
            </div>
          )}
        </>
      ) : !provider.refusal && (
        <p className="muted small">The practice owner chooses this.</p>
      )}
    </Card>
  );
}

/** The practice address on a Microsoft 365 practice: practice owner only. */
function MicrosoftPracticeAddress({ status, onSaved }: {
  status: MicrosoftStatus;
  onSaved: (said: { ok?: string; problem?: string }) => void;
}) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(!status.connected || !status.alias_verified);
  const [address, setAddress] = useState(status.alias);
  const save = useMutation({
    mutationFn: () => api.post<MicrosoftStatus>("/api/microsoft-connection/practice-address/",
                                                { address: address.trim().toLowerCase() }),
    onSuccess: (next) => {
      qc.setQueryData(["microsoft-connection"], next);
      setOpen(!next.connected || !next.alias_verified);
      onSaved(next.verify_error ? { problem: next.verify_error }
        : next.connected ? { ok: `${next.alias} passed its check. App mail will send as it.` }
        : { ok: `Saved. ${next.alias} is checked when you connect Microsoft 365 below.` });
    },
    onError: (e: Error) => onSaved({ problem: e.message }),
  });

  if (!open) {
    return (
      <Card title="Practice address"
        actions={<button className="ghost" onClick={() => setOpen(true)}>Change</button>}>
        <p><strong>{status.alias}</strong></p>
        <p className="muted small">
          Clients see this as the sender of digests, sign-in links and other mail the app
          sends for the practice.
        </p>
      </Card>
    );
  }
  return (
    <Card title="Practice address">
      <p className="small muted" style={{ marginTop: 0 }}>
        The address clients see as the sender. It can be your own work address, or a
        shared mailbox or alias like info@. Currently: <strong>{status.alias}</strong>.
      </p>
      <Field label="Practice address">
        <input type="email" aria-label="Practice address" value={address}
          onChange={(e) => setAddress(e.target.value)} style={{ maxWidth: "24rem" }} />
      </Field>
      <div className="indent small">
        <p><strong>For an address that isn't your own (Microsoft 365):</strong></p>
        <ul>
          <li>A <strong>shared mailbox</strong> or group: an administrator gives you{" "}
            <em>Send as</em> on it, in the Exchange admin center under{" "}
            <em>Recipients → Mailboxes → the mailbox → Delegation</em>.</li>
          <li>An <strong>alias on your own mailbox</strong>: an administrator turns on
            sending from aliases for the organization.</li>
          <li>Then Save. The app sends a short check from that address to your own inbox
            and reads back who Microsoft says it was from. Until it passes, nothing sends.</li>
        </ul>
      </div>
      <div className="row tight wrap">
        <button className="primary" disabled={!address.trim() || save.isPending}
          onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : `Save ${address.trim() || "the practice address"}`}
        </button>
        {status.connected && status.alias_verified && (
          <button onClick={() => setOpen(false)}>Cancel</button>
        )}
      </div>
    </Card>
  );
}

/** Settings → Email on a Microsoft 365 practice. FF and CF only (H7). */
export function MicrosoftEmailSettings({ me, providerCard }: {
  me: Me; providerCard: React.ReactNode;
}) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  const [collectReplies, setCollectReplies] = useState<boolean | null>(null);

  // Microsoft's redirect lands here with its outcome in the query string.
  useEffect(() => {
    const connected = params.get("ms_connected");
    const warning = params.get("ms_warning");
    const error = params.get("ms_error");
    if (connected) setNote(`Connected ${connected}.`);
    if (warning) setProblem(warning);
    if (error) setProblem(error);
    if (connected || warning || error) {
      setParams({}, { replace: true });
      qc.invalidateQueries({ queryKey: ["microsoft-connection"] });
    }
  }, [params, setParams, qc]);

  const status = useQuery<MicrosoftStatus>({
    queryKey: ["microsoft-connection"],
    queryFn: () => api.get<MicrosoftStatus>("/api/microsoft-connection/"),
  });

  const start = useMutation({
    mutationFn: (inbound: boolean) =>
      api.post<{ authorization_url: string }>("/api/microsoft-connection/start/", { inbound }),
    onSuccess: (data) => { window.location.href = data.authorization_url; },
    onError: (e: Error) => setProblem(e.message),
  });
  const verify = useMutation({
    mutationFn: () => api.post<MicrosoftStatus>("/api/microsoft-connection/verify/"),
    onSuccess: (data) => {
      qc.setQueryData(["microsoft-connection"], data);
      if (data.verify_error) { setProblem(data.verify_error); setNote(""); }
      else { setNote(`${data.alias} passed its check. App mail will send as it.`); setProblem(""); }
    },
    onError: (e: Error) => setProblem(e.message),
  });
  const disconnect = useMutation({
    mutationFn: () => api.post<MicrosoftStatus>("/api/microsoft-connection/disconnect/"),
    onSuccess: (data) => {
      qc.setQueryData(["microsoft-connection"], data);
      setNote("Disconnected. The stored token was deleted with the connection.");
      setProblem("");
    },
    onError: (e: Error) => setProblem(e.message),
  });

  const head = (
    <PageHead title="Email settings"
      sub={<>Every app-originated message (sign-in links, digests, referral touches) is
        sent by a connected Microsoft 365 work account with <strong>From</strong> set to
        the practice address. This is your own connection.</>} />
  );
  if (status.isLoading) return <>{head}<p className="muted">Loading…</p></>;
  if (status.isError) {
    return <>{head}<Banner kind="bad">{(status.error as Error).message}</Banner></>;
  }

  const s = status.data!;
  const busy = start.isPending || verify.isPending || disconnect.isPending;
  const inbound = collectReplies ?? s.reads_mail;
  const blocked = !s.configured || Boolean(s.refusal);
  const granted = s.scopes.map(scopeLabel).filter(Boolean);

  return (
    <>
      {head}
      {note && <Banner kind="ok">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}
      {providerCard}
      {!s.configured && !s.refusal && (
        <Banner kind="warn">
          Microsoft 365 isn't set up on this server yet, so there is nothing to connect to.
          Contact support.
        </Banner>
      )}

      {me.role === "FF" && !s.refusal && (
        <MicrosoftPracticeAddress status={s}
          onSaved={(said) => { setNote(said.ok ?? ""); setProblem(said.problem ?? ""); }} />
      )}

      <Card
        title="Your Microsoft 365 connection"
        actions={
          s.connected ? (
            <>
              <button className="primary" disabled={busy || blocked}
                onClick={() => start.mutate(inbound)}>Reconnect</button>
              <button className="danger" disabled={busy}
                onClick={() => disconnect.mutate()}>Disconnect</button>
            </>
          ) : (
            <button className="primary" disabled={busy || blocked}
              onClick={() => start.mutate(inbound)}>Connect Microsoft 365</button>
          )
        }
      >
        {s.connected ? (
          <>
            <p className="wrap-anywhere">
              <Pill kind="ok">connected</Pill> {s.email_address}
              {s.is_sending_connection && <> <Pill kind="ai">practice sending account</Pill></>}
            </p>
            <p className="muted small">Connected {when(s.connected_at)}.</p>
            <p className="muted small">Granted: {granted.length ? granted.join(" · ") : "—"}</p>
          </>
        ) : (
          <>
            <p><Pill kind="warn">not connected</Pill> No Microsoft 365 account is connected
              for you.</p>
            <p className="muted small">
              Connect signs in with your Microsoft 365 <strong>work account</strong> and asks
              for two permissions: send mail as you (<code>Mail.Send</code>), and see who a
              message is from (<code>Mail.ReadBasic</code>, no message bodies), which is how
              the practice address is checked. It asks to read your mailbox only if you tick
              the box below. If your organization lets only administrators approve apps,
              Microsoft says so and the app gives you the link for them.
            </p>
          </>
        )}
        <label className="choice">
          <input type="checkbox" checked={inbound} disabled={busy}
            onChange={(e) => setCollectReplies(e.target.checked)} />
          <span>Also collect replies</span>
        </label>
        <p className="muted small">
          Ticked, Microsoft is also asked for <code>Mail.Read</code>: a read over your{" "}
          <strong>entire mailbox</strong>. Microsoft has no narrower grant. The app reads
          only the conversations it started, but that limit is in the app&apos;s code, not
          enforced by Microsoft. Unticked, Replies cannot collect anything.
          {s.connected && (s.reads_mail
            ? " Your connection holds it now."
            : " Your connection does not hold it; tick the box and Reconnect.")}
        </p>
      </Card>

      <Card
        title="Practice address check"
        actions={s.connected && !s.refusal && (
          <button className="ghost" disabled={busy} onClick={() => verify.mutate()}>
            {verify.isPending ? "Checking…" : s.alias_verified ? "Check again" : "Check now"}
          </button>
        )}
      >
        <p className="wrap-anywhere">
          <strong>{s.alias}</strong>{" "}
          {!s.connected ? <Pill>connect to check</Pill>
            : s.alias_verified ? <Pill kind="ok">passed</Pill>
            : <Pill kind="bad">not yet</Pill>}
        </p>
        <p className="muted small">
          {s.connected && s.alias.toLowerCase() === s.email_address.toLowerCase()
            ? "This is your own address, which Microsoft 365 always lets you send from."
            : "Checked by sending a short message from it to your own inbox and reading back, " +
              "from Sent Items, who Microsoft says it was from."}
        </p>
        {s.alias_verified && <p className="muted small">Passed {when(s.alias_verified_at)}.</p>}
        {s.connected && !s.alias_verified && (
          <Banner kind="warn">
            {s.send_as_error || `${s.alias} hasn't been checked yet.`}
            {" "}Until it passes, nothing sends: there is deliberately no fallback to your
            own address.
          </Banner>
        )}
      </Card>

      <SenderSettings provider="Microsoft 365" />
      {s.is_local_build && <DevAllowlist />}

      <Card title="Practice sending">
        {s.practice_sending.ok ? (
          <p className="muted small wrap-anywhere">
            The practice currently sends through <strong>{s.practice_sending.account}</strong>,
            on Microsoft 365. The Outbox stays the single queue and the complete send log.
            {me.role === "CF" && s.practice_sending.account !== s.email_address &&
              " That is the practice owner's connection, not yours."}
          </p>
        ) : (
          <Banner kind="bad">{s.practice_sending.detail}</Banner>
        )}
      </Card>
    </>
  );
}
