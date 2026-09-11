import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import { Banner, Card, Empty, Pill } from "../components/ui";
import { Company, Me, api } from "../lib/api";
import { AddCompany } from "./AddCompany";

export function Companies({ me }: { me: Me }) {
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");

  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/"),
  });

  return (
    <>
      <div className="spread">
        <h2>Companies</h2>
        {!adding && (
          <button className="primary" onClick={() => { setAdding(true); setNote(""); }}>
            Add company
          </button>
        )}
      </div>
      <p className="sub">Client companies carry a seat count; seats are counted from live logins, never stored.</p>

      {note && <Banner kind="ok">{note}</Banner>}

      {adding && (
        <AddCompany
          me={me}
          onDone={(company) => {
            setAdding(false);
            if (company) {
              setNote(`Added ${company.name}.`);
              navigate(`/companies/${company.id}`);
            }
          }}
        />
      )}

      <Card>
        {(companies.data ?? []).length === 0 ? <Empty>No companies yet — add one above.</Empty> : (
          <table>
            <thead><tr><th>Name</th><th>Industry</th><th>Client</th><th>Seats</th></tr></thead>
            <tbody>
              {companies.data!.map((c) => (
                <tr key={c.id}>
                  <td><Link to={`/companies/${c.id}`}>{c.name}</Link></td>
                  <td className="muted">{c.industry || "—"}</td>
                  <td>{c.is_client_company ? <Pill kind="ok">client</Pill> : <span className="muted">—</span>}</td>
                  <td>{c.seat_count === null ? "—" : `${c.seats_in_use} / ${c.seat_count}`}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
