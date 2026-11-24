/** One owner's agreement: where it stands, the owner's details, the PDFs, the
 *  history, corrections before the owner signs, and countersigning. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { SignatureCapture, hasSignature } from "../components/SignatureCapture";
import { Banner, Card, Pill, when } from "../components/ui";
import type { CapturedSignature, Me } from "../lib/api";
import {
  agreements, SHARED_EMAIL, sharesEmail, type AgreementDetail as Detail, type CoOwnerInput,
  type Terms,
} from "../lib/agreements";
import { AgreementBlocks, CoOwnersEditor, StatusLine, TermsEditor } from "./Agreements";

const PERIOD: Record<string, string> = { winter: "Dec 1 – Mar 31", summer: "Apr 1 – Jul 31",
  fall: "Aug 1 – Nov 30" };

export function AgreementDetail({ me: _me }: { me: Me }) {
  const { id = "" } = useParams();
  const [params] = useSearchParams();
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [owners, setOwners] = useState<CoOwnerInput[] | null>(null);
  const [cancelling, setCancelling] = useState(false);
  const [reason, setReason] = useState("");
  const { data, error } = useQuery({ queryKey: ["agreement", id],
                                     queryFn: () => agreements.get(id) });
  const [said, setSaid] = useState(params.get("copied") ? "Link copied."
    : params.get("emailed") ? "Emailed to the owner." : "");
  const [problem, setProblem] = useState("");
  const [editing, setEditing] = useState<Terms | null>(null);
  const [showText, setShowText] = useState(false);
  if (error) return <div className="page"><Banner kind="warn">{(error as Error).message}
    </Banner></div>;
  if (!data) return <div className="page"><p className="muted">Loading…</p></div>;
  const set = (next: Detail) => qc.setQueryData(["agreement", id], next);
  const act = async (fn: () => Promise<Detail>, message: string) => {
    setProblem("");
    try {
      const out = await fn();
      set(out);
      setSaid(message);
      void qc.invalidateQueries({ queryKey: ["agreements", data.company_id] });
      return out;
    } catch (e) {
      setProblem((e as Error).message);
      return null;
    }
  };
  const d = data.details as Record<string, unknown> & { emergency?: Record<string, string>;
    mailing?: Record<string, string> };
  const fees = Object.entries(data.terms_shown.fees ?? {}).filter(([, r]) => Number(r.fee) > 0);
  return (
    <div className="page agreements">
      <p className="muted small" style={{ margin: 0 }}>
        <Link to={`/agreements?company=${data.company_id}`}>Owner agreements</Link></p>
      <div className="spread wrap" style={{ gap: ".5rem" }}>
        <h1 style={{ margin: ".25rem 0" }}>#{data.number} {data.owner_name}</h1>
        <span className="small" aria-live="polite">{said}</span>
      </div>
      <p className="muted" style={{ marginTop: 0 }}>{data.template}
        {data.property ? ` · ${data.property}` : ""}</p>
      <StatusLine row={data} />
      {problem && <Banner kind="warn">{problem}</Banner>}
      {data.cancelled && <Banner kind="warn">Cancelled{data.cancel_reason
        ? `: ${data.cancel_reason}` : ""}.{data.successor && <> A new agreement was started
        from it: <Link to={`/agreements/${data.successor.id}`}>#{data.successor.number}</Link>.
        </>}</Banner>}
      {data.started_from && <p className="muted small">Started from cancelled agreement
        {" "}<Link to={`/agreements/${data.started_from.id}`}>#{data.started_from.number}</Link>.
        </p>}
      {data.words_problem && <Banner kind="warn">{data.words_problem}</Banner>}
      {data.may_restart && (
        <p><button type="button" className="primary" onClick={async () => {
          setProblem("");
          try {
            const made = await agreements.restart(id);
            void qc.invalidateQueries({ queryKey: ["agreements", data.company_id] });
            navigate(`/agreements/${made.id}`);
          } catch (e) { setProblem((e as Error).message); }
        }}>Start a new agreement from this one</button>
        <span className="muted small"> Copies the terms and the owners into a new draft, and
          moves the owner's intake to it with its answers.</span></p>
      )}

      {data.may_countersign && <Countersign data={data} onDone={(out) => {
        set(out); setSaid("Countersigned. The final copy went to the owner.");
      }} onError={setProblem} />}

      {data.owners.length > 1 && (
        <Card title="Owners" actions={data.editable && data.may_work && !owners
          ? <button type="button" className="small ghost"
              onClick={() => setOwners(data.co_owners)}>Correct</button> : undefined}>
          {owners ? (
            <>
              <p className="muted small">Owner 1: {data.owner_name}</p>
              <CoOwnersEditor rows={owners} onChange={setOwners} />
              {sharesEmail([data.owner_email, ...owners.map((o) => o.email)])
                && <Banner kind="info">{SHARED_EMAIL}</Banner>}
              <div className="agreement-actions">
                <button type="button" className="primary" onClick={async () => {
                  const out = await act(() => agreements.update(id, { co_owners: owners }),
                                        "Owners corrected. Email it again so the first owner "
                                        + "has the corrected agreement.");
                  if (out) setOwners(null);
                }}>Save the owners</button>
                <button type="button" className="ghost" onClick={() => setOwners(null)}>
                  Cancel</button>
              </div>
            </>
          ) : (
            <>
              <ol className="owners-list">
                {data.owners.map((o) => (
                  <li key={o.position}><strong>{o.name}</strong>{o.title ? `, ${o.title}` : ""}
                    {" "}<span className="muted small">{o.email}</span>{" "}
                    {o.signed_at ? <Pill kind="good">Signed {when(o.signed_at)}</Pill>
                      : o.turn ? <Pill kind="warn">Their turn</Pill>
                      : <Pill>Signs in turn</Pill>}</li>
                ))}
              </ol>
              {data.shared_email && <p className="muted small">{SHARED_EMAIL}</p>}
              {!data.editable && !data.cancelled && <p className="muted small">The owners are
                fixed once the first owner has signed. To change them, cancel this agreement and
                start a new one from it.</p>}
            </>
          )}
        </Card>
      )}

      {data.may_work && data.turn_position !== null && (() => {
        const next = data.owners.find((o) => o.turn);
        const who = data.owners.length > 1 && next ? next.name : "the owner";
        const email = data.turn_position === 1 ? data.owner_email : next?.email;
        return (
        <Card title="Send">
          <div className="agreement-actions">
            <button type="button" className="primary" disabled={!email}
              onClick={() => void act(() => agreements.action(id, "send"),
                                      `Emailed to ${who}.`)}>
              {data.turn_position === 1 && !data.status[0].at ? "Send by email"
                : data.owners.length > 1 ? `Email ${who} again` : "Email it again"}</button>
            <button type="button" className="ghost" onClick={async () => {
              const out = await act(() => agreements.action(id, "link"), "Link copied.");
              if (out?.link) await navigator.clipboard?.writeText(out.link)
                .catch(() => setSaid(out.link ?? ""));
            }}>{data.owners.length > 1 ? `Copy ${who}'s link` : "Copy the link"}</button>
          </div>
          {!email && <p className="muted small">No email for this owner: copy the
            link and send it yourself.</p>}
          {data.sender === "testing" && <p className="muted small">Owner email is on ENHQ's own
            sender (testing): the owner would see Executives Now.</p>}
        </Card>
        );
      })()}

      <Card title="Terms" actions={data.editable && data.may_work && !editing
        ? <button type="button" className="small ghost"
            onClick={() => setEditing(data.terms)}>Correct</button> : undefined}>
        {editing ? (
          <>
            <TermsEditor terms={editing} onChange={setEditing} />
            <p className="muted small">The owner's link opens the corrected agreement.</p>
            <div className="agreement-actions">
              <button type="button" className="primary" onClick={async () => {
                const out = await act(() => agreements.update(id, { terms: editing }),
                                      "Corrected.");
                if (out) setEditing(null);
              }}>Save the correction</button>
              <button type="button" className="ghost" onClick={() => setEditing(null)}>
                Cancel</button>
            </div>
          </>
        ) : (
          <dl className="terms-summary">
            <dt>Split</dt><dd>Owner {data.terms_shown.owner_percent}% · Manager
              {" "}{data.terms_shown.manager_percent}%</dd>
            <dt>Contract in Track</dt><dd>{data.contract.name || <Pill kind="warn">
              {data.contract.flag}</Pill>}</dd>
            <dt>Minimum revenue fee</dt><dd>{fees.length ? fees.map(([k, r]) => (
              <div key={k}>{PERIOD[k]}: under ${r.threshold} a month, fee ${r.fee} a month</div>
            )) : "None"}</dd>
            <dt>Additional items</dt><dd>{data.terms_shown.additional_items || "None"}</dd>
            <dt>Version</dt><dd>{data.version}</dd>
          </dl>
        )}
      </Card>

      {data.address_changed && (
        <Banner kind="warn">The owner corrected the property's address: you entered
          {" "}<strong>{data.staff_address}</strong>; the owner signed with
          {" "}<strong>{data.owner_address}</strong>.</Banner>
      )}

      {data.owner_signature && (
        <Card title="The owner's details">
          <dl className="terms-summary">
            <dt>Signed by</dt><dd>{data.owner_signature.name}, {when(data.owner_signature.at)}
              {data.owner_signature.ip ? ` · IP ${data.owner_signature.ip}` : ""}</dd>
            {d.owner_type === "entity" && <><dt>Owner of record</dt>
              <dd>{String(d.entity_name ?? "")}, {String(d.signer_title ?? "")}</dd></>}
            <dt>Phone · email</dt><dd>{String(d.phone ?? "")} · {String(d.email ?? "")}</dd>
            <dt>Mailing address</dt><dd>{[d.mailing?.street, d.mailing?.street2,
              d.mailing?.city, d.mailing?.state, d.mailing?.zip].filter(Boolean).join(", ")}</dd>
            <dt>Bedrooms · bathrooms · sq ft</dt><dd>{String(d.bedrooms ?? "")} ·
              {" "}{String(d.bathrooms ?? "")} · {String(d.square_feet ?? "—")}</dd>
            <dt>Emergency contact</dt><dd>{[d.emergency?.name, d.emergency?.phone,
              d.emergency?.address].filter(Boolean).join(", ")}</dd>
          </dl>
        </Card>
      )}

      <Card title="Documents">
        <ul className="plain">
          <li><a href={agreements.pdfUrl(id, "preview")} target="_blank" rel="noreferrer">
            Preview the agreement (PDF)</a></li>
          {data.has_owner_pdf && <li><a href={agreements.pdfUrl(id, "owner")} target="_blank"
            rel="noreferrer">Signed by {data.owners.length > 1 ? "every owner" : "the owner"},
            awaiting SkyRun's signature (PDF)</a></li>}
          {data.has_final_pdf && <li><a href={agreements.pdfUrl(id, "final")} target="_blank"
            rel="noreferrer"><strong>Final, signed by both (PDF)</strong></a>
            {data.agreement_date && <> · dated {data.agreement_date}</>}</li>}
        </ul>
        {data.intake && (
          <p>Owner intake: {data.intake.may_open
            ? <Link to={`/intake/${data.intake.id}`}>#{data.intake.number}</Link>
            : `#${data.intake.number}`} <Pill>{data.intake.status.replace("_", " ")}</Pill></p>
        )}
        {data.manager_signature && (
          <p className="small">SkyRun's signature ({data.signer_block}):
            {data.manager_signature.under_authority
              ? ` applied by ${data.manager_signature.applied_by} under the authorization `
                + `${data.manager_signature.authority_by} recorded`
              : ` signed personally by ${data.manager_signature.applied_by}`},
            {" "}{when(data.manager_signature.at)}.</p>
        )}
        {data.may_download_text && (
          <p className="small"><a href={agreements.signedTextUrl(id)}>The words the owner signed
            (text)</a>: its SHA-256 is "Words signed" on the signing record.</p>
        )}
      </Card>

      <Card title="The agreement" actions={<button type="button" className="small ghost"
        onClick={() => setShowText(!showText)}>{showText ? "Hide" : "Show"}</button>}>
        {showText ? <AgreementBlocks blocks={data.blocks} />
          : <p className="muted small">The words as the owner reads them, terms
            highlighted.</p>}
      </Card>

      <Card title="History">
        <ul className="plain history">
          {data.events.map((e, i) => <li key={i}><span className="when">{when(e.at)}</span>
            {" "}{e.detail}{e.by ? ` (${e.by})` : ""}</li>)}
          {data.emails.map((m, i) => <li key={`m${i}`}><span className="when">{when(m.at)}</span>
            {" "}Email to the owner ({m.kind.replace("_", " ")}): {m.state}
            {m.error ? `: ${m.error}` : ""}</li>)}
        </ul>
      </Card>

      {data.may_cancel && (cancelling ? (
        <Card title="Cancel this agreement">
          <p className="small">The owners' links stop working.
            {data.owners.some((o) => o.signed_at) ? " Every owner who has already signed is "
              + "emailed that the agreement was withdrawn and that SkyRun will be in touch."
              : " Nobody is emailed: no owner has signed yet."}</p>
          <label className="field"><span>Why is it being cancelled? (recorded)</span>
            <textarea rows={2} value={reason} maxLength={300}
              onChange={(e) => setReason(e.target.value)} /></label>
          <div className="agreement-actions">
            <button type="button" className="danger" disabled={!reason.trim()} onClick={async () => {
              const out = await act(() => agreements.cancel(id, reason), "Cancelled.");
              if (out) { setCancelling(false); setReason(""); }
            }}>Cancel the agreement</button>
            <button type="button" className="ghost" onClick={() => setCancelling(false)}>
              Keep it</button>
          </div>
        </Card>
      ) : (
        <p><button type="button" className="small ghost danger"
          onClick={() => setCancelling(true)}>Cancel this agreement</button></p>
      ))}
    </div>
  );
}

function Countersign({ data, onDone, onError }: { data: Detail; onDone: (d: Detail) => void;
  onError: (m: string) => void }) {
  const [agreed, setAgreed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [sig, setSig] = useState<CapturedSignature>({ method: "typed", typed: "", drawn: "" });
  const signer = data.countersign_as === "signer";
  const needsMark = signer && !data.authority;
  // The exact words, from the server: the record keeps the same ones.
  const words = data.countersign_words;
  return (
    <Card title="Countersign for SkyRun" tone="current">
      {data.address_changed && <Banner kind="warn">The owner changed the address: you
        entered <strong>{data.staff_address}</strong>; the owner signed with
        {" "}<strong>{data.owner_address}</strong>. Check it before countersigning.</Banner>}
      <p>{data.owner_signatures.length > 1
        ? `Every owner has signed, the last on ${when(data.owner_signatures[
          data.owner_signatures.length - 1].at)}.`
        : `${data.owner_signature?.name} signed on ${when(data.owner_signature?.at)}.`} The
        agreement's date will be today's.</p>
      {needsMark ? (
        <SignatureCapture value={sig} onChange={setSig} consent={words} agreed={agreed}
          onAgree={setAgreed} />
      ) : (
        <>
          {data.authority && (
            <div className="sig-preview">
              {data.authority.method === "typed"
                ? <span className="sig-typed">{data.authority.typed}</span>
                : <span className="muted">{data.signer_name}'s drawn signature</span>}
            </div>
          )}
          <label className="sig-consent">
            <input type="checkbox" checked={agreed} onChange={(e) => setAgreed(e.target.checked)}
              aria-label="I agree" />
            <span>{words}</span>
          </label>
        </>
      )}
      <button type="button" className="primary big" disabled={!agreed || busy
        || (needsMark && !hasSignature(sig))} onClick={async () => {
          setBusy(true);
          try {
            onDone(await agreements.countersign(data.id, needsMark
              ? { agreed, method: sig.method, typed: sig.typed, drawn: sig.drawn }
              : { agreed }));
          } catch (e) {
            onError((e as Error).message);
          } finally {
            setBusy(false);
          }
        }}>{busy ? "Countersigning…" : signer ? "Countersign"
          : "Apply SkyRun's signature"}</button>
    </Card>
  );
}
