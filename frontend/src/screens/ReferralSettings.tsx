import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { api, Contact } from "../lib/api";

interface Settings {
  referral_blurb: string;
  referral_blurb_updated_at: string | null;
  blurb_age_days: number | null;
  marketing_flyer: string | null;
  marketing_flyer_name: string;
}

export function ReferralSettings() {
  const qc = useQueryClient();
  const [blurb, setBlurb] = useState<string | null>(null);
  const [note, setNote] = useState("");

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
      <h2>Referral settings</h2>
      <p className="sub">
        The blurb is the substance of every touch. The flyer rides along on a partner's
        first follow-up.
      </p>

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
        {s?.marketing_flyer
          ? <p><Pill kind="ok">attached</Pill> {s.marketing_flyer_name}</p>
          : <p className="muted small">No flyer uploaded.</p>}
        <input type="file" accept="application/pdf"
          onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); }} />
      </Card>

      <Card title={`Referral partners (${partners.length})`}>
        {partners.length === 0 ? (
          <Empty>
            No referral partners yet. Open a contact and use “Make a referral partner”.
          </Empty>
        ) : (
          <table>
            <thead>
              <tr><th>Name</th><th>Cadence</th><th>Mode</th><th>Fee terms</th><th>Next touch</th></tr>
            </thead>
            <tbody>
              {partners.map((p) => (
                <tr key={p.id}>
                  <td><Link to={`/contacts/${p.id}`}>{p.first_name} {p.last_name}</Link></td>
                  <td>{p.referral_cadence || "monthly"}</td>
                  <td>{p.referral_touch_mode === "ai"
                    ? <Pill kind="ai">AI-drafted</Pill> : <Pill>my template</Pill>}</td>
                  <td className="muted small">{p.referral_fee_terms || "—"}</td>
                  <td className="muted small">{when(p.referral_next_touch_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
