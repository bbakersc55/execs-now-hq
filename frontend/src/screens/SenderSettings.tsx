import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Field } from "../components/ui";
import { api } from "../lib/api";

interface Preference {
  sender_by_producer: Record<string, string>;
  signature_text: string;
  effective: Record<string, string>;
  available: { alias: string; self: string };
}

const PRODUCERS: { key: string; label: string; hint: string }[] = [
  { key: "referral_touch", label: "Referral touches",
    hint: "A partner asked for introductions should hear from a person." },
  { key: "referral_onboarding", label: "Referral onboarding",
    hint: "The first touch after meeting someone." },
  { key: "stage_rule", label: "Stage-rule emails",
    hint: "Automated follow-ups triggered by a pipeline move." },
  { key: "manual", label: "One-off and bulk emails",
    hint: "Anything you compose yourself." },
];

/** FR-1.15c/d — who app mail comes from, and how it signs off. */
export function SenderSettings() {
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [signature, setSignature] = useState<string | null>(null);

  const preference = useQuery<Preference>({
    queryKey: ["mail-preference"],
    queryFn: () => api.get<Preference>("/api/mail-preference/"),
  });

  const save = useMutation({
    mutationFn: (body: Partial<Preference>) => api.post("/api/mail-preference/", body),
    onSuccess: () => {
      setNote("Saved. New drafts use this; drafts already in the Outbox keep the address they were created with.");
      qc.invalidateQueries({ queryKey: ["mail-preference"] });
    },
    onError: (e: Error) => setNote(e.message),
  });

  const p = preference.data;
  const ownVerified = !!p?.available.self;

  return (
    <Card title="Who your mail comes from">
      {note && <Banner kind="ok">{note}</Banner>}

      <p className="muted small">
        Both options are limited to <strong>verified send-as addresses</strong> — Gmail
        refuses anything else, so offering a choice that failed at send time would be
        worse than not offering it.
      </p>

      {!ownVerified && (
        <Banner kind="warn">
          Your own address is not a verified send-as address yet, so everything goes from
          the practice alias. Connect Gmail and verify the alias above to unlock it.
        </Banner>
      )}

      <table>
        <thead><tr><th>These emails</th><th>Come from</th></tr></thead>
        <tbody>
          {PRODUCERS.map((producer) => (
            <tr key={producer.key}>
              <td>
                {producer.label}
                <div className="muted small">{producer.hint}</div>
              </td>
              <td>
                <select
                  aria-label={producer.label}
                  value={p?.effective[producer.key] ?? "alias"}
                  onChange={(e) => save.mutate({
                    sender_by_producer: {
                      ...(p?.sender_by_producer ?? {}),
                      [producer.key]: e.target.value,
                    },
                  })}
                >
                  <option value="alias">
                    The practice alias{p ? ` — ${p.available.alias}` : ""}
                  </option>
                  <option value="self" disabled={!ownVerified}>
                    My own address{p?.available.self ? ` — ${p.available.self}` : " (not verified)"}
                  </option>
                </select>
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      <Field label="Signature">
        <textarea rows={4} aria-label="Signature"
          value={signature ?? p?.signature_text ?? ""}
          placeholder={"Your name\nThe practice name"}
          onChange={(e) => setSignature(e.target.value)} />
        <p className="muted small">
          Signs off every touch and one-off email. Left blank it defaults to your full
          name over the practice name — a bare practice name under a personal note reads
          as a form letter.
        </p>
      </Field>
      <button className="primary" disabled={save.isPending}
        onClick={() => save.mutate({ signature_text: signature ?? p?.signature_text ?? "" })}>
        Save signature
      </button>
    </Card>
  );
}
