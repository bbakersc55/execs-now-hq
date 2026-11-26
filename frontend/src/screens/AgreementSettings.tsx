/** Owner agreement settings: who may do what (one permissions screen, owner
 *  2026-11-23), the owner email sender, and who signs for the company; and
 *  the signer's own standing authorization. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { SignatureCapture, hasSignature } from "../components/SignatureCapture";
import { Banner, Card, when } from "../components/ui";
import type { CapturedSignature, Me } from "../lib/api";
import { agreements, type Program } from "../lib/agreements";
import { apart, roleByName } from "../lib/people";
import { Labeled } from "./Agreements";

export function AgreementSettings({ me: _me }: { me: Me }) {
  const { companyId = "" } = useParams();
  const page = useQuery({ queryKey: ["agreements", companyId],
                          queryFn: () => agreements.company(companyId) });
  const canEdit = !!page.data?.may_edit_access;
  const [program, setProgram] = useState<Program | null>(null);
  const [said, setSaid] = useState("");
  const [problem, setProblem] = useState("");
  useEffect(() => { if (page.data) setProgram(page.data.program); }, [page.data]);
  if (page.error) return <div className="page"><Banner kind="warn">
    {(page.error as Error).message}</Banner></div>;
  if (!page.data || !program) return <div className="page"><p className="muted">Loading…</p></div>;
  return (
    <div className="page agreements">
      <p className="muted small" style={{ margin: 0 }}>
        <Link to={`/agreements?company=${companyId}`}>Owner agreements</Link></p>
      <div className="spread"><h1 style={{ margin: ".25rem 0" }}>Settings</h1>
        <span className="small" aria-live="polite">{said}</span></div>
      {problem && <Banner kind="warn">{problem}</Banner>}

      {canEdit && (
        <Card title="People and permissions">
          <p style={{ margin: 0 }}>Who may send agreements, who receives signed PDFs, and who
            runs intakes: <Link to={`/permissions/${companyId}`}>People and permissions</Link>.</p>
        </Card>
      )}

      <Card title="Who signs for the company">
        <p style={{ marginTop: 0 }}>The agreement's signature block reads
          {" "}<strong>Michael LeClerc, President</strong>.
          {program.signer_name ? <> In ENHQ that is <strong>{program.signer_name}</strong>.</>
            : " Nobody in ENHQ is set as the signer yet, so nobody can countersign."}</p>
        {program.may_set_signer && (
          <SignerPicker program={program} companyId={companyId} onSaved={(p) => {
            setProgram(p); setSaid("Saved.");
          }} onError={setProblem} />
        )}
        <p className="muted small">The signer records a standing authorization naming who may
          apply their signature. Until then only the signer can countersign.</p>
      </Card>

      <SenderCard program={program} companyId={companyId} canEdit={canEdit}
        onChange={(p, message) => { setProgram(p); setSaid(message); }}
        onError={setProblem} />
    </div>
  );
}

function SignerPicker({ program, companyId, onSaved, onError }: { program: Program;
  companyId: string; onSaved: (p: Program) => void; onError: (m: string) => void }) {
  const { data } = useQuery({ queryKey: ["agreement-authority", companyId],
                              queryFn: () => agreements.authority(companyId) });
  const people = (data?.people ?? []).filter((p) => p.role !== "Practice owner");
  const nameOf = apart(people, roleByName);
  return (
    <Labeled label="The signer in ENHQ">
      <select value={program.signer_id ?? ""} onChange={async (e) => {
        try { onSaved(await agreements.saveSettings(companyId, { signer_id: e.target.value })); }
        catch (err) { onError((err as Error).message); }
      }}>
        <option value="">Nobody yet</option>
        {people.map((p) => <option key={p.user_id} value={p.user_id}>{nameOf(p)}</option>)}
      </select>
    </Labeled>
  );
}

function SenderCard({ program, companyId, canEdit, onChange, onError }: { program: Program;
  companyId: string; canEdit: boolean; onChange: (p: Program, message: string) => void;
  onError: (m: string) => void }) {
  const [draft, setDraft] = useState(program);
  useEffect(() => setDraft(program), [program]);
  const save = async (body: Record<string, unknown>, message: string) => {
    try { onChange(await agreements.saveSettings(companyId, body), message); }
    catch (e) { onError((e as Error).message); }
  };
  return (
    <Card title="Owner email">
      {program.paused_at && (
        <Banner kind="warn">Owner emails are paused since {when(program.paused_at)}:
          {" "}{program.pause_reason} {program.held} waiting. Nothing goes out another way.
          <div style={{ marginTop: ".5rem" }}><button type="button" className="small primary"
            onClick={async () => {
              try {
                const out = await agreements.settingsAction(companyId, "resume");
                onChange(out, out.message ?? "Resumed.");
              } catch (e) { onError((e as Error).message); }
            }}>Resume owner emails</button></div></Banner>
      )}
      <fieldset disabled={!canEdit}>
        <label className="radio-line">
          <input type="radio" checked={program.sender === "testing"}
            onChange={() => void save({ sender: "testing" }, "Saved.")} />
          <span><strong>ENHQ's own sender (testing)</strong>
            <br /><span className="small muted">Owners would see Executives Now as the
              sender.</span></span>
        </label>
        <label className="radio-line">
          <input type="radio" checked={program.sender === "domain"}
            disabled={!program.domain_ready}
            onChange={() => void save({ sender: "domain" }, "Saved.")} />
          <span><strong>Our own domain</strong><br /><span className="small muted">
            {program.domain_ready ? `From ${program.from_address}.`
              : "Set the domain and the addresses, then Send a test to me."}</span></span>
        </label>
        {program.sender === "testing" && <Banner kind="warn">{program.warning}</Banner>}
        <div className="sender-fields">
          <Labeled label="Domain"><input value={draft.sender_domain} placeholder="example.com"
            onChange={(e) => setDraft({ ...draft, sender_domain: e.target.value })} /></Labeled>
          <Labeled label="From address"><input type="email" value={draft.from_address}
            onChange={(e) => setDraft({ ...draft, from_address: e.target.value })} /></Labeled>
          <Labeled label="From name"><input value={draft.from_name}
            onChange={(e) => setDraft({ ...draft, from_name: e.target.value })} /></Labeled>
          <Labeled label="Replies go to"><input type="email" value={draft.reply_to}
            onChange={(e) => setDraft({ ...draft, reply_to: e.target.value })} /></Labeled>
        </div>
        <div className="agreement-actions">
          <button type="button" className="ghost" onClick={() => void save({
            sender_domain: draft.sender_domain, from_address: draft.from_address,
            from_name: draft.from_name, reply_to: draft.reply_to }, "Saved.")}>Save</button>
          <button type="button" className="ghost" onClick={async () => {
            try {
              const out = await agreements.settingsAction(companyId, "test");
              onChange(out, out.message ?? "Sent.");
            } catch (e) { onError((e as Error).message); }
          }}>Send a test to me</button>
        </div>
        {program.tested_at && <p className="small muted">Last test that worked:
          {" "}{when(program.tested_at)}.</p>}
      </fieldset>
    </Card>
  );
}

// ------------------------------------------------------------ the signer's authorization

export function AgreementAuthority({ me: _me }: { me: Me }) {
  const { companyId = "" } = useParams();
  const qc = useQueryClient();
  const { data, error } = useQuery({ queryKey: ["agreement-authority", companyId],
                                     queryFn: () => agreements.authority(companyId) });
  const [sig, setSig] = useState<CapturedSignature>({ method: "typed", typed: "", drawn: "" });
  const [agreed, setAgreed] = useState(false);
  const [people, setPeople] = useState<string[] | null>(null);
  const [problem, setProblem] = useState("");
  const [said, setSaid] = useState("");
  useEffect(() => {
    if (data && people === null) {
      setPeople(data.authority ? data.authority.people.map((p) => p.user_id) : []);
    }
  }, [data, people]);
  if (error) return <div className="page"><Banner kind="warn">{(error as Error).message}
    </Banner></div>;
  if (!data || people === null) return <div className="page"><p className="muted">Loading…</p>
    </div>;
  const save = (out: unknown, message: string) => {
    qc.setQueryData(["agreement-authority", companyId], out);
    setSaid(message);
    setAgreed(false);
  };
  const current = data.authority;
  return (
    <div className="page agreements">
      <p className="muted small" style={{ margin: 0 }}>
        <Link to={`/agreements?company=${companyId}`}>Owner agreements</Link></p>
      <div className="spread"><h1 style={{ margin: ".25rem 0" }}>Your standing authorization</h1>
        <span className="small" aria-live="polite">{said}</span></div>
      {problem && <Banner kind="warn">{problem}</Banner>}
      {!data.is_signer && <Banner kind="warn">Only {data.signer_name} records this, signed in
        as themselves.</Banner>}
      {current ? (
        <Card title={`In force since ${current.recorded_on}`}>
          <p style={{ marginTop: 0 }}>{current.principal}'s signature may be applied to new-owner
            agreements by: <strong>{current.people.map(apart(current.people, roleByName))
              .join(", ") || "nobody else"}</strong>.</p>
          {current.method === "typed" && <p className="sig-typed">{current.typed}</p>}
          {data.is_signer && <button type="button" className="ghost danger"
            onClick={async () => {
              if (!window.confirm("Withdraw it? From now on only you can countersign.")) return;
              try { save(await agreements.withdraw(companyId), "Withdrawn."); }
              catch (e) { setProblem((e as Error).message); }
            }}>Withdraw it</button>}
        </Card>
      ) : (
        <Banner kind="info">There's no authorization in force: only {data.signer_name} can
          countersign.</Banner>
      )}
      {data.is_signer && (
        <Card title={current ? "Record a new one (it replaces this)" : "Record your authorization"}>
          <p style={{ marginTop: 0 }}>Adopt your signature, and choose who may apply it.</p>
          <fieldset>
            <legend>Who may apply it</legend>
            {data.people.map((p) => (
              <label key={p.user_id} className="check-line">
                <input type="checkbox" checked={people.includes(p.user_id)}
                  onChange={(e) => setPeople(e.target.checked ? [...people, p.user_id]
                    : people.filter((x) => x !== p.user_id))} />
                <span>{p.name} <span className="small muted">({p.role})</span></span>
              </label>
            ))}
          </fieldset>
          <SignatureCapture value={sig} onChange={setSig} consent={data.wording}
            agreed={agreed} onAgree={setAgreed} />
          <button type="button" className="primary" disabled={!agreed || !hasSignature(sig)}
            onClick={async () => {
              setProblem("");
              try {
                save(await agreements.record(companyId, { method: sig.method, typed: sig.typed,
                  drawn: sig.drawn, people, agreed }), "Recorded.");
              } catch (e) { setProblem((e as Error).message); }
            }}>Record the authorization</button>
        </Card>
      )}
    </div>
  );
}
