import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useParams } from "react-router-dom";

import { Banner, Card, Empty, Pill, when, positionsLabel } from "../components/ui";
import { AddCompany } from "./AddCompany";
import { Company, Contact, Me, api } from "../lib/api";
import { PortalAccessCard, usePortalAccess } from "../components/PortalAccessCard";

interface TimelineEntry { kind: string; when: string; text: string; note_id?: string; locked?: boolean; }

export function CompanyDetail({ me }: { me: Me }) {
  const { id } = useParams();
  const [editing, setEditing] = useState(false);
  const [note, setNote] = useState("");
  const [error, setError] = useState("");
  const qc = useQueryClient();
  const company = useQuery<Company>({
    queryKey: ["company", id], queryFn: () => api.get<Company>(`/api/companies/${id}/`),
  });
  const timeline = useQuery<TimelineEntry[]>({
    queryKey: ["company-timeline", id],
    queryFn: () => api.get<TimelineEntry[]>(`/api/companies/${id}/timeline/`),
  });
  const contacts = useQuery<Contact[]>({
    queryKey: ["contacts"], queryFn: () => api.get<Contact[]>("/api/contacts/"),
  });

  // Matrix 4.8 — the FF, or a CF (who only reaches assigned companies). Never a VA.
  const maySetPrimary = me.role === "FF" || me.role === "CF";
  const setPrimary = useMutation({
    mutationFn: (contact: string) =>
      api.patch<Company>(`/api/companies/${id}/`, { primary_contact: contact }),
    onSuccess: (updated, contact) => {
      const who = (contacts.data ?? []).find((x) => x.id === contact);
      setError("");
      setNote(`${who ? `${who.first_name} ${who.last_name}` : "They"} is now the primary contact. `
        + "Future grants offer them as founder; nobody's existing portal role changed.");
      qc.setQueryData(["company", id], updated);
      qc.invalidateQueries({ queryKey: ["companies"] });
      qc.invalidateQueries({ queryKey: ["portal-candidates", id] });
      qc.invalidateQueries({ queryKey: ["portal-candidate"] });
    },
    onError: (e: Error) => { setNote(""); setError(e.message); },
  });

  // Seat usage comes from the same query the Portal access card reads, so the
  // header and the card move together (and a VA, who sees neither, gets neither).
  const company_ = company.data;
  const access = usePortalAccess(me, company_ ?? ({ id: id!, is_client_company: false } as Company));

  if (company.isError) return <Banner kind="bad">That company is not available to you.</Banner>;
  if (!company_) return <p>Loading…</p>;
  const c = company_;
  const theirs = (contacts.data ?? []).filter((x) => x.company === c.id);
  const seats = access.data;

  if (editing) {
    return (
      <AddCompany
        me={me}
        existing={c}
        people={theirs}
        onDone={(updated) => {
          setEditing(false);
          if (updated) {
            setNote("Company updated.");
            qc.invalidateQueries({ queryKey: ["company", id] });
            qc.invalidateQueries({ queryKey: ["companies"] });
            qc.invalidateQueries({ queryKey: ["portal-candidates", id] });
          }
        }}
      />
    );
  }

  return (
    <>
      <div className="spread">
        <h2>{c.name}</h2>
        <button onClick={() => setEditing(true)}>Edit company</button>
      </div>
      {note && <Banner kind="ok">{note}</Banner>}
      {error && <Banner kind="bad">{error}</Banner>}
      <p className="sub">
        {c.industry || "No industry"}
        {c.is_client_company && <> · <Pill kind="ok">client company</Pill></>}
        {seats && seats.seat_count !== null
          && <> · {seats.seats_in_use} of {seats.seat_count} seats used</>}
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: "1.15rem" }}>
        <Card title={`People (${theirs.length})`}>
          {theirs.length === 0 ? <Empty>No contacts at this company.</Empty> : (
            <table>
              <thead><tr><th>Name</th><th>Title</th><th>Stage</th>{maySetPrimary && <th></th>}</tr></thead>
              <tbody>
                {theirs.map((p) => (
                  <tr key={p.id}>
                    <td>
                      <Link to={`/contacts/${p.id}`}>{p.first_name} {p.last_name}</Link>
                      {c.primary_contact === p.id && <> <Pill>primary contact</Pill></>}
                    </td>
                    <td className="muted">{p.title || "—"}</td>
                    <td className="small">{positionsLabel(p.pipeline_positions)}</td>
                    {maySetPrimary && (
                      <td>
                        {c.primary_contact !== p.id && (
                          <button className="ghost small" disabled={setPrimary.isPending}
                            aria-label={`Set ${p.first_name} ${p.last_name} as primary contact`}
                            onClick={() => setPrimary.mutate(p.id)}>
                            Set as primary contact
                          </button>
                        )}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <PortalAccessCard me={me} company={c} />

        <Card title="Timeline">
          {(timeline.data ?? []).length === 0 ? <Empty>Nothing yet.</Empty> : (
            <ul className="timeline">
              {timeline.data!.map((e, i) => (
                <li key={i}>
                  <div>{e.note_id
                    ? <Link to={`/notes/${e.note_id}`}>{e.locked && "🔒 "}{e.text}</Link>
                    : e.text}</div>
                  <div className="when">{e.kind} · {when(e.when)}</div>
                </li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
