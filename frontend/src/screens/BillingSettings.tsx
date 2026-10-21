import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageHead } from "../components/shell";
import { Banner, Card, Field, Pill, when } from "../components/ui";
import { api } from "../lib/api";
import { YourSubscription } from "./YourSubscription";

/** GET /api/payment-account/ — never a key, only the last four of each. */
export interface PaymentAccountState {
  environment: "sandbox" | "live";
  private_key_last4: string;
  public_key_last4: string;
  checked_at: string | null;
  check_ok: boolean | null;
  check_detail: string;
  ready: boolean;
  live_allowed: boolean;
  gateway: "nmi" | "stub";
  pricing_program: "" | "interchange_plus" | "dual_pricing";
  pricing_program_label: string;
}

/**
 * Settings → Billing (P4, matrix 12.1): the practice owner's own NMI account,
 * which client payments will go to. Write-only, as the Anthropic key is: a
 * key is never shown again, and new keys are tested before anything changes.
 */
export function BillingSettings() {
  const qc = useQueryClient();
  const state = useQuery<PaymentAccountState>({
    queryKey: ["payment-account"],
    queryFn: () => api.get<PaymentAccountState>("/api/payment-account/") });
  const [environment, setEnvironment] = useState<"sandbox" | "live" | null>(null);
  const [privateKey, setPrivateKey] = useState("");
  const [publicKey, setPublicKey] = useState("");
  const [problem, setProblem] = useState("");
  const [note, setNote] = useState("");

  const done = (data: PaymentAccountState, text: string) => {
    qc.setQueryData(["payment-account"], data);
    setPrivateKey(""); setPublicKey(""); setEnvironment(null);
    setProblem(""); setNote(text);
  };
  const failed = (e: Error) => { setNote(""); setProblem(e.message); };
  const save = useMutation({
    mutationFn: () => api.post<PaymentAccountState>("/api/payment-account/", {
      environment: environment ?? s?.environment, private_key: privateKey,
      public_key: publicKey }),
    onSuccess: (data) => done(data, "NMI accepted the keys. They are saved."),
    onError: failed,
  });
  const test = useMutation({
    mutationFn: () => api.post<PaymentAccountState>("/api/payment-account/test/"),
    onSuccess: (data) => done(data, data.check_ok ? "Connected." : ""),
    onError: failed,
  });

  const s = state.data;
  if (state.isError) return <Banner kind="bad">{(state.error as Error).message}</Banner>;
  if (!s) return <p>Loading the billing settings…</p>;
  const chosen = environment ?? s.environment;
  const hasKeys = Boolean(s.private_key_last4 && s.public_key_last4);
  const switching = hasKeys && chosen !== s.environment;

  return (
    <>
      <PageHead title="Billing"
        sub="Your own NMI account, which your clients' card payments will go to." />
      {s.gateway === "stub" && (
        <Banner kind="warn">Card payments are switched off on this server. The connection
          test answers from a stand-in, and nothing reaches NMI.</Banner>
      )}
      {note && <Banner kind="ok">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}

      <Card title="Taking card payments">
        <p style={{ marginTop: 0 }}>
          {s.ready ? <Pill kind="ok">Connected</Pill>
            : s.check_ok === false ? <Pill kind="bad">The last test failed</Pill>
            : <Pill kind="warn">Not connected</Pill>}{" "}
          {hasKeys && (
            <span className="small muted">
              {s.environment === "live" ? "Live" : "Sandbox (test)"} · private key
              <span className="mono"> …{s.private_key_last4}</span> · public key
              <span className="mono"> …{s.public_key_last4}</span>
              {s.checked_at && <> · tested {when(s.checked_at)}</>}
            </span>
          )}
        </p>
        {s.check_ok === false && s.check_detail && <Banner kind="bad">{s.check_detail}</Banner>}

        <form onSubmit={(e) => { e.preventDefault(); save.mutate(); }}>
          <Field label="Environment">
            <div className="row tight">
              <label className="check">
                <input type="radio" name="environment" checked={chosen === "sandbox"}
                  onChange={() => setEnvironment("sandbox")} /> Sandbox (test)
              </label>
              <label className="check">
                <input type="radio" name="environment" checked={chosen === "live"}
                  disabled={!s.live_allowed} onChange={() => setEnvironment("live")} /> Live
              </label>
            </div>
          </Field>
          {!s.live_allowed && (
            <p className="small muted">Live keys are accepted only on the production app.</p>
          )}
          <div className="row" style={{ flexWrap: "wrap", gap: "0.75rem" }}>
            <Field label="Private API key">
              <input aria-label="Private API key" type="password" autoComplete="off"
                placeholder={s.private_key_last4 && !switching
                  ? `Stored: …${s.private_key_last4}` : ""}
                value={privateKey} onChange={(e) => setPrivateKey(e.target.value)} />
            </Field>
            <Field label="Public tokenization key">
              <input aria-label="Public tokenization key" type="password" autoComplete="off"
                placeholder={s.public_key_last4 && !switching
                  ? `Stored: …${s.public_key_last4}` : ""}
                value={publicKey} onChange={(e) => setPublicKey(e.target.value)} />
            </Field>
          </div>
          {switching && (
            <p className="small muted">Sandbox and live keys are different keys: enter both
              of the {chosen === "live" ? "live" : "sandbox"} ones.</p>
          )}
          <div className="row tight">
            <button className="primary" type="submit"
              disabled={save.isPending || (!privateKey.trim() && !publicKey.trim() && !switching)}>
              {save.isPending ? "Testing…" : "Test and save"}</button>
            <button className="ghost" type="button" disabled={!hasKeys || test.isPending}
              onClick={() => test.mutate()}>
              {test.isPending ? "Testing…" : "Test connection"}</button>
          </div>
        </form>
        <p className="small muted">
          Both keys are in your NMI account's settings, under Security Keys. New keys are
          tested with NMI before they are saved; if NMI refuses them, nothing changes. They are
          stored encrypted and never shown again. The test proves the private key; the public
          key is proved the first time a card form uses it.
        </p>
        <p className="small" style={{ marginBottom: 0 }}>
          Pricing program: <strong>{s.pricing_program_label || "Not set yet"}</strong>.{" "}
          <span className="muted">Set when your practice was set up. To change it, contact
            Executives Now.</span>
        </p>
      </Card>
      <YourSubscription />
    </>
  );
}
