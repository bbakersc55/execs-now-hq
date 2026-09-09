import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";

import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { api, Company, Contact } from "../lib/api";

interface TimelineEntry { kind: string; when: string; text: string; }

export function CompanyDetail() {
  const { id } = useParams();
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

  if (company.isError) return <Banner kind="bad">That company is not available to you.</Banner>;
  if (!company.data) return <p>Loading…</p>;
  const c = company.data;
  const theirs = (contacts.data ?? []).filter((x) => x.company === c.id);

  return (
    <>
      <h2>{c.name}</h2>
      <p className="sub">
        {c.industry || "No industry"}
        {c.is_client_company && <> · <Pill kind="ok">client company</Pill></>}
        {c.seat_count !== null && <> · {c.seats_in_use} of {c.seat_count} seats used</>}
      </p>

      <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: "1.15rem" }}>
        <Card title={`People (${theirs.length})`}>
          {theirs.length === 0 ? <Empty>No contacts at this company.</Empty> : (
            <table>
              <thead><tr><th>Name</th><th>Title</th><th>Stage</th></tr></thead>
              <tbody>
                {theirs.map((p) => (
                  <tr key={p.id}>
                    <td><Link to={`/contacts/${p.id}`}>{p.first_name} {p.last_name}</Link></td>
                    <td className="muted">{p.title || "—"}</td>
                    <td>{p.stage_code?.replace(/_/g, " ") || "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>

        <Card title="Timeline">
          {(timeline.data ?? []).length === 0 ? <Empty>Nothing yet.</Empty> : (
            <ul className="timeline">
              {timeline.data!.map((e, i) => (
                <li key={i}><div>{e.text}</div><div className="when">{e.kind} · {when(e.when)}</div></li>
              ))}
            </ul>
          )}
        </Card>
      </div>
    </>
  );
}
