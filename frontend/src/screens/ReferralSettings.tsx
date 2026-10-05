import { PageHead, useRowLink } from "../components/shell";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { BulkBar } from "../components/BulkBar";
import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { api, Contact } from "../lib/api";

interface Settings {
  referral_blurb: string;
  referral_blurb_updated_at: string | null;
  blurb_age_days: number | null;
  marketing_flyer: string | null;
  marketing_flyer_name: string;
  marketing_flyer_bytes: number;
  /** null when storage could not be reached to check — not the same as missing. */
  marketing_flyer_present: boolean | null;
}

export function ReferralSettings() {
  const rowLink = useRowLink();
  const qc = useQueryClient();
  const [blurb, setBlurb] = useState<string | null>(null);
  const [note, setNote] = useState("");
  const [picked, setPicked] = useState<string[]>([]);

  const settings = useQuery<Settings>({
    queryKey: ["referral-settings"],
    queryFn: () => api.get<Settings>("/api/referral-settings/"),
  });
  const contacts = useQuery<Contact[]>({
    queryKey: ["contacts"], queryFn: () => api.get<Contact[]>("/api/contacts/"),
  });

  const save = useMutation({
    mutationFn: (body: { referral_blurb: string }) =>
      api.post("/api/referral-settings/", body),
    onSuccess: () => {
      setNote("Blurb saved. Its age resets, so touch drafts stop warning about it.");
      qc.invalidateQueries({ queryKey: ["referral-settings"] });
    },
  });

  const draftTouch = useMutation({
    mutationFn: (contactId: string) =>
      api.post(`/api/contacts/${contactId}/draft-touch/`),
    onSuccess: () => {
      setNote("Touch drafted into the Outbox, pending approval. Nothing was sent.");
      qc.invalidateQueries({ queryKey: ["outbox"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  // Enrollment is explicit (owner, 2026-09-28): a partner gets touches only
  // once someone here has put them on the cadence.
  const enrol = useMutation({
    mutationFn: ({ ids, off }: { ids: string[]; off: boolean }) =>
      api.post<{ changed_count: number; skipped: { name: string; detail: string }[] }>(
        "/api/contacts/enroll-selected/",
        { ids, program: "referral_touches", ...(off ? { unenroll: true } : {}) }),
    onSuccess: (r, { off }) => {
      const skipped = r.skipped.length
        ? ` ${r.skipped.length} skipped: ${r.skipped.map((x) => `${x.name} (${x.detail})`).join(", ")}.`
        : "";
      setNote(off
        ? `${r.changed_count} unenrolled. Their unapproved touches were withdrawn.${skipped}`
        : `${r.changed_count} enrolled. Touches will be drafted for approval as each falls due.${skipped}`);
      setPicked([]);
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["outbox"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const draftMany = useMutation({
    mutationFn: () => api.post<{ drafted_count: number; skipped: { name: string; detail: string }[] }>(
      "/api/contacts/draft-touches/", { ids: picked },
    ),
    onSuccess: (r) => {
      const skipped = r.skipped.length
        ? ` ${r.skipped.length} skipped: ${r.skipped.map((x) => `${x.name} (${x.detail})`).join(", ")}.`
        : "";
      setNote(
        `${r.drafted_count} touches drafted into the Outbox, one per partner, all pending approval.${skipped}`,
      );
      setPicked([]);
      qc.invalidateQueries({ queryKey: ["outbox"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const upload = useMutation({
    mutationFn: (file: File) => {
      const form = new FormData();
      form.append("flyer", file);
      return api.post("/api/referral-settings/flyer/", form);
    },
    onSuccess: () => {
      setNote("Flyer uploaded. New onboarding drafts will attach it.");
      qc.invalidateQueries({ queryKey: ["referral-settings"] });
    },
  });

  const partners = (contacts.data ?? []).filter((c) => c.type_codes.includes("referral_partner"));
  const s = settings.data;
  const stale = s?.blurb_age_days != null && s.blurb_age_days > 30;

  return (
    <>
      <PageHead title="Referral settings"
        sub="The blurb is the substance of every touch. The flyer rides along on a partner's
        first follow-up." />

      {note && <Banner kind="ok">{note}</Banner>}
      {stale && (
        <Banner kind="warn">
          Your blurb was last updated {s!.blurb_age_days} days ago. Touch drafts will carry
          a staleness warning until you refresh it.
        </Banner>
      )}

      <Card title="What I'm working on lately">
        <p className="muted small">
          Three to five lines. This is what makes a touch worth a partner's attention.
        </p>
        <textarea
          rows={5}
          value={blurb ?? s?.referral_blurb ?? ""}
          onChange={(e) => setBlurb(e.target.value)}
        />
        <div style={{ marginTop: ".6rem" }} className="spread">
          <span className="muted small">Last updated {when(s?.referral_blurb_updated_at)}</span>
          <button className="primary" disabled={save.isPending}
            onClick={() => save.mutate({ referral_blurb: blurb ?? s?.referral_blurb ?? "" })}>
            Save blurb
          </button>
        </div>
      </Card>

      <Card title="Marketing flyer">
        <p className="muted small">
          Optional. When set, it is attached to every new referral-partner onboarding
          draft. Without one, the draft is still created and says so.
        </p>
        {s?.marketing_flyer ? (
          <>
            <p>
              <Pill kind={s.marketing_flyer_present === null ? ""
                : s.marketing_flyer_present ? "ok" : "bad"}>
                {s.marketing_flyer_present === null ? "storage unreachable — could not check"
                  : s.marketing_flyer_present ? "attached" : "file missing"}
              </Pill>{" "}
              {s.marketing_flyer_name}
              {s.marketing_flyer_present
                && ` · ${Math.max(1, Math.round(s.marketing_flyer_bytes / 1024))} KB`}
            </p>
            {s.marketing_flyer_present === false && (
              <Banner kind="bad">
                This flyer was uploaded before the app stored file content, so the record
                exists but the file does not. <strong>Re-upload it below.</strong> Until
                you do, any send that would attach it is refused rather than delivering an
                empty document.
              </Banner>
            )}
          </>
        ) : <p className="muted small">No flyer uploaded.</p>}
        <input type="file" accept="application/pdf"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); }} />
      </Card>

      <Card title={`Referral partners (${partners.length})`}>
        {partners.length > 0 && (
          <BulkBar
            total={partners.length} selected={picked.length}
            onSelectAll={() => setPicked(partners.map((p) => p.id))}
            onClear={() => setPicked([])}
          >
            <button className="primary" disabled={!picked.length || enrol.isPending}
              onClick={() => enrol.mutate({ ids: picked, off: false })}>
              Enroll {picked.length || ""} selected
            </button>
            <button disabled={!picked.length || enrol.isPending}
              onClick={() => enrol.mutate({ ids: picked, off: true })}>
              Unenroll selected
            </button>
            <button disabled={!picked.length || draftMany.isPending}
              onClick={() => draftMany.mutate()}>
              Draft touch for {picked.length || ""} selected
            </button>
          </BulkBar>
        )}
        {partners.length > 0 && (
          <p className="small muted">
            <strong>{partners.filter((p) => p.referral_enrolled).length} of {partners.length}
            {" "}enrolled.</strong> Touches are drafted only for enrolled partners — becoming a
            partner, or being imported as one, does not enroll anyone.
          </p>
        )}
        {partners.length === 0 ? (
          <Empty>
            No referral partners yet. Open a contact and use “Make a referral partner”.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr><th></th><th>Name</th><th>Touches</th><th>Cadence</th><th>Mode</th><th>Fee terms</th><th>Next touch</th><th></th></tr>
            </thead>
            <tbody>
              {partners.map((p) => (
                <tr key={p.id} {...rowLink(`/contacts/${p.id}`)}>
                  <td>
                    <input type="checkbox" checked={picked.includes(p.id)}
                      aria-label={`Select ${p.first_name} ${p.last_name}`}
                      onChange={(e) => setPicked(e.target.checked
                        ? [...picked, p.id]
                        : picked.filter((x) => x !== p.id))} />
                  </td>
                  <td><Link className="rowname" to={`/contacts/${p.id}`}>{p.first_name} {p.last_name}</Link></td>
                  <td>
                    <span className="inline">
                      {p.referral_enrolled
                        ? <Pill kind="ok">enrolled</Pill> : <Pill>not enrolled</Pill>}
                      <button className="small" disabled={enrol.isPending}
                        aria-label={`${p.referral_enrolled ? "Unenroll" : "Enroll"} ${p.first_name} ${p.last_name}`}
                        onClick={() => enrol.mutate({ ids: [p.id], off: !!p.referral_enrolled })}>
                        {p.referral_enrolled ? "Unenroll" : "Enroll"}
                      </button>
                    </span>
                  </td>
                  <td>{p.referral_cadence || "monthly"}</td>
                  <td>{p.referral_touch_mode === "ai"
                    ? <Pill kind="ai">AI-drafted</Pill> : <Pill>my template</Pill>}</td>
                  <td className="muted small">{p.referral_fee_terms || "—"}</td>
                  <td className="muted small">
                    {!p.referral_enrolled ? "—"
                      : p.referral_next_touch_at ? when(p.referral_next_touch_at)
                      : <Pill kind="warn">none set</Pill>}
                  </td>
                  <td className="right">
                    <button disabled={draftTouch.isPending || !p.referral_enrolled}
                      title={p.referral_enrolled ? undefined : "Enroll them first"}
                      aria-label={`Draft touch for ${p.first_name} ${p.last_name}`}
                      onClick={() => draftTouch.mutate(p.id)}>
                      Draft touch now
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
