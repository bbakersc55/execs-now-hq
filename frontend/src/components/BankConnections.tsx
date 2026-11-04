import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Pill, when } from "./ui";
import { BankConnection, BankOverview, FinanceAccount, api } from "../lib/api";
import { dollars, longDate } from "../lib/money";

/**
 * Bank feeds (docs/p6_bank_feeds.md): the practice owner's own bank accounts,
 * connected through Plaid and feeding Finance.
 *
 * The full card lives in Settings → Finance: each connection, its accounts and
 * the ledger account each one feeds, the last sync, Check now, Reconnect and
 * Disconnect. Finance → Import shows the short form, with Connect a bank.
 */

type PlaidHandler = { open(): void; exit(): void; destroy(): void };
type PlaidLink = {
  create(options: {
    token: string;
    onSuccess: (publicToken: string, metadata: unknown) => void;
    onExit: (error: { display_message?: string; error_message?: string } | null) => void;
  }): PlaidHandler;
};
declare global { interface Window { Plaid?: PlaidLink } }

/** Plaid's own widget, which it requires be loaded from its CDN. */
const LINK_SRC = "https://cdn.plaid.com/link/v2/stable/link-initialize.js";
let loading: Promise<PlaidLink> | null = null;

export function loadPlaidLink(): Promise<PlaidLink> {
  if (window.Plaid) return Promise.resolve(window.Plaid);
  if (!loading) {
    loading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = LINK_SRC;
      script.async = true;
      script.onload = () => (window.Plaid ? resolve(window.Plaid)
        : reject(new Error("The bank's sign-in did not load.")));
      script.onerror = () => {
        loading = null;
        reject(new Error("The bank's sign-in could not be loaded. Check the connection "
          + "and try again."));
      };
      document.head.appendChild(script);
    });
  }
  return loading;
}

const QUERY = ["finance-bank"];

/** Opens Plaid Link for a new connection, or (with `connection`) in update
 *  mode to repair one. Resolves with the public token, or null if closed. */
async function openLink(connection?: string): Promise<string | null> {
  const made = await api.post<{ link_token: string }>("/api/finance-bank/link-token/",
    connection ? { connection } : {});
  const Plaid = await loadPlaidLink();
  return new Promise((resolve, reject) => {
    const handler = Plaid.create({
      token: made.link_token,
      onSuccess: (publicToken) => { handler.destroy(); resolve(publicToken); },
      onExit: (error) => {
        handler.destroy();
        if (error) reject(new Error(error.display_message || error.error_message
          || "The bank's sign-in stopped before it finished."));
        else resolve(null);
      },
    });
    handler.open();
  });
}

function useBank() {
  return useQuery<BankOverview>({
    queryKey: QUERY, queryFn: () => api.get<BankOverview>("/api/finance-bank/") });
}

function countLine(data: BankOverview) {
  return `${data.price_line}. You have ${data.count} connected.`;
}

function ConnectButton({ onSaid, onDone }: {
  onSaid: (text: string) => void; onDone: (text: string) => void;
}) {
  const qc = useQueryClient();
  const connect = useMutation({
    mutationFn: async () => {
      const publicToken = await openLink();
      if (!publicToken) return null;
      return api.post<BankConnection>("/api/finance-bank/connect/",
        { public_token: publicToken });
    },
    onSuccess: (made) => {
      if (!made) return;
      onSaid("");
      onDone(`${made.institution} is connected. Choose where each account's lines go, `
        + "in Settings, Finance, Bank connections.");
      qc.invalidateQueries({ queryKey: QUERY });
    },
    onError: (e: Error) => onSaid(e.message),
  });
  return (
    <button className="primary" disabled={connect.isPending} onClick={() => connect.mutate()}>
      {connect.isPending ? "Connecting…" : "Connect a bank"}</button>
  );
}

function statusPill(connection: BankConnection) {
  return connection.status === "connected" ? <Pill kind="ok">Connected</Pill>
    : connection.status === "needs_attention" ? <Pill kind="warn">Needs attention</Pill>
      : <Pill>Disconnected</Pill>;
}

function synced(connection: BankConnection) {
  return connection.last_synced_at ? `Last synced ${when(connection.last_synced_at)}`
    : "Not synced yet";
}

/** Finance → Import: the short form. */
export function BankFeedsOnImport() {
  const bank = useBank();
  const [said, setSaid] = useState("");
  const [done, setDone] = useState("");
  const data = bank.data;
  if (!data) return null;
  if (!data.available) {
    return <p className="small muted" aria-label="Bank feeds">Bank feeds aren't set up on
      this server yet, so bring your bank's lines in with a file below.</p>;
  }
  return (
    <Card title="Bank feeds" actions={<ConnectButton onSaid={setSaid} onDone={setDone} />}>
      {said && <Banner kind="bad">{said}</Banner>}
      {done && <Banner kind="ok">{done}</Banner>}
      <p className="small muted" style={{ marginTop: 0 }}>
        A connected bank brings its lines into the books every night, and whenever the bank
        says there is something new. Files are still welcome below, for the months before a
        feed began or an account without one.
      </p>
      {data.connections.length === 0 ? <Empty>No bank connected yet.</Empty> : (
        <ul className="plain" aria-label="Connected banks" style={{ margin: 0, paddingLeft: 0,
                                                                   listStyle: "none" }}>
          {data.connections.map((c) => (
            <li key={c.id} style={{ marginBottom: "var(--s2)" }}>
              <strong>{c.institution}</strong> {statusPill(c)}{" "}
              <span className="small muted">
                {c.accounts.filter((a) => a.finance_account).length} of {c.accounts.length}{" "}
                accounts fed · {synced(c)}</span>
              {c.waiting > 0 && <> <Pill kind="warn">{c.waiting} to map</Pill></>}
            </li>
          ))}
        </ul>
      )}
      <p className="small" style={{ marginBottom: 0 }}>
        <span className="muted">{countLine(data)}</span>{" "}
        <Link to="/settings/finance#bank-connections">Manage bank connections</Link>
      </p>
    </Card>
  );
}

/** Settings → Finance: the whole card. */
export function BankConnectionsCard({ reconnectId }: { reconnectId?: string | null }) {
  const bank = useBank();
  const accounts = useQuery<FinanceAccount[]>({
    queryKey: ["finance-accounts"],
    queryFn: () => api.get<FinanceAccount[]>("/api/finance-accounts/") });
  const [said, setSaid] = useState("");
  const [done, setDone] = useState("");
  const data = bank.data;
  if (!data || !data.available) return null;
  const ledgers = (accounts.data ?? []).filter((a) => !a.closed);
  return (
    <div id="bank-connections">
      <Card title="Bank connections"
        actions={<ConnectButton onSaid={setSaid} onDone={setDone} />}>
        {said && <Banner kind="bad">{said}</Banner>}
        {done && <Banner kind="ok">{done}</Banner>}
        {data.demo && <Banner kind="info">{data.refusal}</Banner>}
        <p className="small muted" style={{ marginTop: 0 }}>
          Your own bank accounts, connected through Plaid. Each account feeds one of the
          accounts you reconcile: its lines become entries, its balance is your cash today in
          the forecast, and it is offered as the ending balance when you reconcile. Lines
          already in your books are not brought in again.
        </p>
        <p className="small" aria-label="Bank connections included">
          {countLine(data)} Nothing is charged for them yet.</p>
        {data.connections.length === 0 && <Empty>No bank connected yet.</Empty>}
        {data.connections.map((c) => (
          <Connection key={c.id} connection={c} ledgers={ledgers}
            highlighted={reconnectId === c.id} onSaid={setSaid} onDone={setDone} />
        ))}
        {data.disconnected.length > 0 && (
          <p className="small muted" style={{ marginBottom: 0 }}>
            Disconnected: {data.disconnected.map((c) => `${c.institution} (on `
              + `${c.disconnected_at ? longDate(c.disconnected_at.slice(0, 10)) : "—"})`)
              .join(", ")}. Their entries are kept.</p>
        )}
      </Card>
    </div>
  );
}

function Connection({ connection: c, ledgers, highlighted, onSaid, onDone }: {
  connection: BankConnection; ledgers: FinanceAccount[]; highlighted: boolean;
  onSaid: (text: string) => void; onDone: (text: string) => void;
}) {
  const qc = useQueryClient();
  const refresh = () => {
    for (const key of ["finance-bank", "finance-entries", "finance-pnl", "finance-balance",
                       "finance-forecast", "finance-reconcile"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
  const fail = (e: Error) => { onDone(""); onSaid(e.message); };
  const base = `/api/finance-bank/${c.id}/`;
  const map = useMutation({
    mutationFn: (body: Record<string, string>) => api.post<BankConnection>(
      base + "mapping/", { mapping: body }),
    onSuccess: () => { onSaid(""); refresh(); }, onError: fail });
  const check = useMutation({
    mutationFn: () => api.post<BankConnection & { counts: BankConnection["last_sync_counts"] }>(
      base + "check/", {}),
    onSuccess: (made) => {
      onSaid("");
      const n = made.counts ?? {};
      onDone(n.waiting ? `${c.institution}: balances updated. Map every account to bring `
        + "lines in." : `${c.institution}: ${n.added ?? 0} new, ${n.modified ?? 0} changed, `
        + `${n.removed ?? 0} removed.`);
      refresh();
    },
    onError: fail });
  const reconnect = useMutation({
    mutationFn: async () => {
      const token = await openLink(c.id);
      if (!token) return null;
      return api.post<BankConnection>(base + "reconnected/", {});
    },
    onSuccess: (made) => {
      if (!made) return;
      onSaid(""); onDone(`${c.institution} is reconnected.`); refresh();
    },
    onError: fail });
  const disconnect = useMutation({
    mutationFn: () => api.post<BankConnection>(base + "disconnect/", {}),
    onSuccess: () => { onSaid(""); onDone(`${c.institution} is disconnected. Its entries `
      + "are kept."); refresh(); },
    onError: fail });
  const busy = map.isPending || check.isPending || reconnect.isPending || disconnect.isPending;
  const waitUntil = c.can_check_at && new Date(c.can_check_at) > new Date()
    ? c.can_check_at : null;
  return (
    <section aria-label={`Bank connection ${c.institution}`}
      style={{ borderTop: "1px solid var(--line)", paddingTop: "var(--s3)",
               marginTop: "var(--s3)",
               ...(highlighted ? { outline: "2px solid var(--orange, #F58220)",
                                   outlineOffset: "4px", borderRadius: "4px" } : {}) }}>
      <div className="spread" style={{ flexWrap: "wrap", gap: "var(--s2)" }}>
        <div>
          <strong>{c.institution}</strong> {statusPill(c)}
          <div className="small muted">{synced(c)}
            {c.last_sync_counts.added ? ` · ${c.last_sync_counts.added} new last time` : ""}
          </div>
        </div>
        <div className="row tight" style={{ flexWrap: "wrap" }}>
          {c.reconnect && (
            <button className="primary small" disabled={busy}
              onClick={() => reconnect.mutate()}>Reconnect</button>
          )}
          <button className="small" disabled={busy || Boolean(waitUntil)}
            title={waitUntil ? `Check now again after ${when(waitUntil)}` : undefined}
            onClick={() => check.mutate()}>Check now</button>
          <button className="ghost small" disabled={busy}
            aria-label={`Disconnect ${c.institution}`}
            onClick={() => {
              if (confirm(`Disconnect ${c.institution}? The bank stops sharing with the `
                + "app and nothing more comes in. Every entry it brought in is kept.")) {
                disconnect.mutate();
              }
            }}>Disconnect</button>
        </div>
      </div>
      {c.reconnect && (
        <Banner kind="warn">{c.institution}{" "}
          {c.attention_code === "ITEM_LOGIN_REQUIRED" ? "needs you to sign in to it again."
            : c.attention_code.startsWith("PENDING_")
              ? "will stop sharing soon unless you reconnect." : "has stopped updating."}
          {c.attention_detail && <> The bank said: {c.attention_detail}</>}{" "}
          Choose Reconnect.</Banner>
      )}
      {waitUntil && <p className="small muted" style={{ margin: "var(--s1) 0 0" }}>
        Checked within the hour; Check now opens again after {when(waitUntil)}.</p>}
      {c.waiting > 0 && (
        <Banner kind="info">Choose where each account's lines go. Nothing is brought in until
          every account has a place, or is set not to feed.</Banner>
      )}
      {c.last_error && c.status === "connected" && (
        <p className="small muted">The last sync said: {c.last_error}</p>
      )}
      {/* Rows that wrap rather than a table, so the picker stays whole on a phone. */}
      <ul aria-label={`Accounts at ${c.institution}`}
        style={{ listStyle: "none", margin: "var(--s2) 0 0", padding: 0 }}>
        {c.accounts.map((a) => (
          <li key={a.id} style={{ display: "flex", flexWrap: "wrap", alignItems: "center",
                                  gap: "var(--s2) var(--s3)", padding: "var(--s2) 0",
                                  borderTop: "1px solid var(--line)" }}>
            <div style={{ flex: "1 1 200px", minWidth: 0 }}>
              {a.name}{a.mask && <span className="muted"> ·· {a.mask}</span>}
              <div className="tiny muted">{a.subtype || a.type}</div>
            </div>
            <div className="money" style={{ flex: "0 0 auto", textAlign: "right" }}>
              {a.balance_cents === null ? "—" : dollars(a.balance_cents)}
              <div className="tiny muted">{a.type === "credit" ? "owed" : "balance"}</div>
            </div>
            <div style={{ flex: "1 1 240px", minWidth: 0 }}>
              <select aria-label={`Ledger account for ${a.name}`} disabled={busy}
                style={{ width: "100%" }}
                value={a.finance_account?.id ?? (a.skipped ? "none" : "")}
                onChange={(e) => map.mutate({ [a.id]: e.target.value === "none" ? ""
                  : e.target.value })}>
                {!a.finance_account && !a.skipped && <option value="">Feeds… choose</option>}
                <option value="none">Don't feed</option>
                {ledgers.map((l) => (
                  <option key={l.id} value={l.id}>Feeds {l.name}
                    {l.last4 ? ` ·· ${l.last4}` : ""}</option>
                ))}
              </select>
              <div className="tiny muted">{a.finance_account && a.feed_from
                ? `Lines from ${longDate(a.feed_from)}` : a.skipped ? "Not fed"
                  : "Choose where its lines go"}</div>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
