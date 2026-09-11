import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";

import { Banner, Card, Pill, positionsLabel } from "../components/ui";
import { api, Contact } from "../lib/api";

/** Fields the reviewer resolves by hand. Everything else — emails, phones,
 *  types, categories, notes, tasks, stage history, email history — moves to the
 *  survivor automatically and is never dropped. */
const FIELDS: { key: keyof Contact; label: string }[] = [
  { key: "first_name", label: "First name" },
  { key: "last_name", label: "Last name" },
  { key: "title", label: "Title" },
  { key: "source", label: "Source" },
  { key: "background", label: "Background" },
  { key: "referral_fee_terms", label: "Referral fee terms" },
];

function value(c: Contact | undefined, key: keyof Contact): string {
  if (!c) return "";
  const v = c[key];
  return typeof v === "string" ? v : v == null ? "" : String(v);
}

export function Merge() {
  const { aId, bId } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();

  const [survivorId, setSurvivorId] = useState<string | null>(null);
  const [choices, setChoices] = useState<Record<string, string>>({});
  const [error, setError] = useState("");

  const a = useQuery<Contact>({
    queryKey: ["contact", aId], queryFn: () => api.get<Contact>(`/api/contacts/${aId}/`),
  });
  const b = useQuery<Contact>({
    queryKey: ["contact", bId], queryFn: () => api.get<Contact>(`/api/contacts/${bId}/`),
  });

  // Default the survivor to the older record — it usually carries more history.
  useEffect(() => {
    if (a.data && b.data && survivorId === null) {
      setSurvivorId(a.data.created_at! <= b.data.created_at! ? a.data.id : b.data.id);
    }
  }, [a.data, b.data, survivorId]);

  const survivor = survivorId === a.data?.id ? a.data : b.data;
  const absorbed = survivorId === a.data?.id ? b.data : a.data;

  // Whenever the survivor changes, reset every choice to the survivor's value.
  useEffect(() => {
    if (!survivor) return;
    const next: Record<string, string> = {};
    FIELDS.forEach((f) => { next[f.key as string] = value(survivor, f.key); });
    setChoices(next);
  }, [survivorId]);

  const merge = useMutation({
    mutationFn: () => api.post("/api/contacts/merge/", {
      survivor: survivor!.id, absorbed: absorbed!.id, fields: choices,
    }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["contact", survivor!.id] });
      qc.invalidateQueries({ queryKey: ["timeline", survivor!.id] });
      navigate(`/contacts/${survivor!.id}?merged=1`);
    },
    onError: (e: Error) => setError(e.message),
  });

  if (a.isError || b.isError) {
    return <Banner kind="bad">One of those contacts is not available to you.</Banner>;
  }
  if (!a.data || !b.data || !survivor || !absorbed) return <p>Loading…</p>;

  const conflicts = FIELDS.filter(
    (f) => value(a.data, f.key) !== value(b.data, f.key)
  );

  return (
    <>
      <h2>Merge two contacts</h2>
      <p className="sub">
        All history — notes, tasks, emails, stage changes, types, categories —
        moves to the survivor. The other record is kept, marked merged, and its
        link still resolves here.
      </p>

      {error && <Banner kind="bad">{error}</Banner>}

      <Card title="1. Which record survives?">
        <div className="row">
          {[a.data, b.data].map((c) => (
            <label
              key={c.id}
              className="card"
              style={{
                cursor: "pointer", margin: 0,
                borderColor: survivorId === c.id ? "var(--orange)" : "var(--border)",
                borderWidth: survivorId === c.id ? 2 : 1,
              }}
            >
              <div className="spread">
                <strong>
                  <input
                    type="radio" name="survivor" checked={survivorId === c.id}
                    onChange={() => setSurvivorId(c.id)}
                    style={{ width: "auto", marginRight: ".5rem" }}
                  />
                  {c.first_name} {c.last_name}
                </strong>
                {survivorId === c.id
                  ? <Pill kind="ok">survives</Pill>
                  : <Pill kind="bad">merged away</Pill>}
              </div>
              <div className="muted small" style={{ marginTop: ".4rem" }}>
                {c.emails.map((e) => <div key={e.id} className="mono">{e.address}</div>)}
                {c.title && <div>{c.title}</div>}
                <div>
                  {c.type_codes.length} type{c.type_codes.length === 1 ? "" : "s"} ·{" "}
                  {positionsLabel(c.pipeline_positions)}
                </div>
                <div>Created {new Date(c.created_at!).toLocaleDateString()}</div>
              </div>
            </label>
          ))}
        </div>
      </Card>

      <Card title={`2. Resolve field conflicts (${conflicts.length})`}>
        {conflicts.length === 0 ? (
          <p className="muted small">
            These records do not disagree on any field. Nothing to resolve.
          </p>
        ) : (
          <>
            <p className="muted small">
              Pick the value to keep on the survivor. Defaults to the survivor's own value.
            </p>
            <table>
              <thead>
                <tr>
                  <th style={{ width: "18%" }}>Field</th>
                  <th>{survivor.first_name} {survivor.last_name} <Pill kind="ok">survivor</Pill></th>
                  <th>{absorbed.first_name} {absorbed.last_name} <Pill kind="bad">merged away</Pill></th>
                </tr>
              </thead>
              <tbody>
                {conflicts.map((f) => {
                  const sv = value(survivor, f.key);
                  const av = value(absorbed, f.key);
                  const chosen = choices[f.key as string] ?? sv;
                  return (
                    <tr key={f.key as string}>
                      <td><strong>{f.label}</strong></td>
                      {[sv, av].map((candidate, i) => (
                        <td
                          key={i}
                          onClick={() => setChoices({ ...choices, [f.key as string]: candidate })}
                          style={{
                            cursor: "pointer",
                            background: chosen === candidate ? "#fdf1e5" : undefined,
                            outline: chosen === candidate ? "2px solid var(--orange)" : "none",
                            outlineOffset: "-2px",
                          }}
                        >
                          <input
                            type="radio" name={`f-${f.key as string}`}
                            checked={chosen === candidate}
                            onChange={() => setChoices({ ...choices, [f.key as string]: candidate })}
                            style={{ width: "auto", marginRight: ".5rem" }}
                          />
                          {candidate || <span className="muted">(empty)</span>}
                        </td>
                      ))}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </>
        )}
      </Card>

      <Card title="3. What will happen">
        <ul className="small" style={{ margin: 0, paddingLeft: "1.1rem" }}>
          <li>
            <strong>{absorbed.first_name} {absorbed.last_name}</strong>'s notes, tasks,
            emails, stage history, contact types, and service categories move to{" "}
            <strong>{survivor.first_name} {survivor.last_name}</strong>.
          </li>
          <li>
            Email addresses and phone numbers move across and keep working; only the
            survivor's own stays marked primary.
          </li>
          <li>
            The merged-away record is <strong>soft-deleted, not destroyed</strong>, and its
            link still resolves to the survivor.
          </li>
          <li>The merge is recorded in the audit log with your name on it.</li>
        </ul>
        <div style={{ marginTop: "1rem" }}>
          <button className="primary" disabled={merge.isPending} onClick={() => merge.mutate()}>
            {merge.isPending ? "Merging…" : `Merge into ${survivor.first_name} ${survivor.last_name}`}
          </button>{" "}
          <button onClick={() => navigate(-1)}>Cancel</button>
        </div>
      </Card>
    </>
  );
}
