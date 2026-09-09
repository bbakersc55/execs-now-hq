import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Card, Empty, Pill } from "../components/ui";
import { api, Company } from "../lib/api";

export function Companies() {
  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/"),
  });

  return (
    <>
      <h2>Companies</h2>
      <p className="sub">Client companies carry a seat count; seats are counted from live logins, never stored.</p>
      <Card>
        {(companies.data ?? []).length === 0 ? <Empty>No companies yet.</Empty> : (
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
