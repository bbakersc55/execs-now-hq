import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";

import {
  Avatar, Chip, FilterBar, PageHead, SearchField, Sheet, Sort, SortHeader, sorted,
} from "../components/shell";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { Company, Me, api } from "../lib/api";
import { AddCompany } from "./AddCompany";

/**
 * Companies (design brief, Tier 2).
 *
 * **A table, because these are records.** Records are compared across rows —
 * which of these is a client, which has seats left — and a grid of cards makes
 * that comparison impossible. What the pass adds is everything around the
 * table: an avatar so a name is recognised before it is read, sortable
 * headers, instant search, filter chips that say what is narrowing the list,
 * and a peek before the full page.
 */
export function Companies({ me }: { me: Me }) {
  const navigate = useNavigate();
  const [adding, setAdding] = useState(false);
  const [note, setNote] = useState("");
  const [term, setTerm] = useState("");
  const [active, setActive] = useState("");
  const [onlyClients, setOnlyClients] = useState(false);
  const [sort, setSort] = useState<Sort>({ key: "name", asc: true });
  const [peek, setPeek] = useState<Company | null>(null);
  // Matrix 9.5 — seat usage is not a VA's to see.
  const maySeeSeats = me.role === "FF" || me.role === "CF";

  useEffect(() => {
    const timer = setTimeout(() => setActive(term.trim().toLowerCase()), 200);
    return () => clearTimeout(timer);
  }, [term]);

  const companies = useQuery<Company[]>({
    queryKey: ["companies"], queryFn: () => api.get<Company[]>("/api/companies/"),
  });

  const all = companies.data ?? [];
  const rows = all.filter((c) =>
    (!onlyClients || c.is_client_company)
    && (!active || `${c.name} ${c.industry}`.toLowerCase().includes(active)));
  const shown = sorted(rows, sort, (c) => ({
    name: c.name,
    industry: c.industry,
    client: c.is_client_company ? 0 : 1,
    seats: c.seats_in_use ?? -1,
  }[sort.key] ?? ""));

  return (
    <>
      <PageHead title="Companies"
        sub="Client companies carry a seat count; seats are counted from live logins, never stored."
        action={!adding && (
          <button className="primary" onClick={() => { setAdding(true); setNote(""); }}>
            Add company
          </button>
        )} />

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

      <div className="listbar">
        <SearchField label="Search companies" value={term} onChange={setTerm}
          placeholder="Search companies…" />
        <div className="addfilter">
          <label className="choice">
            <input type="checkbox" checked={onlyClients}
              onChange={(e) => setOnlyClients(e.target.checked)} />
            <span>Clients only</span>
          </label>
        </div>
      </div>

      {(onlyClients || active) && (
        <FilterBar onClearAll={() => { setOnlyClients(false); setTerm(""); }}>
          {active && <Chip label={`Search: ${term.trim()}`} onClear={() => setTerm("")} />}
          {onlyClients && <Chip label="Clients only"
            onClear={() => setOnlyClients(false)} />}
        </FilterBar>
      )}

      <Card>
        {shown.length === 0 ? (
          <Empty>
            {all.length === 0 ? "No companies yet — add one above."
              : "No companies match those filters."}
          </Empty>
        ) : (
          <table className="records">
            <thead>
              <tr>
                <SortHeader label="Name" field="name" sort={sort} onSort={setSort} />
                <SortHeader label="Industry" field="industry" sort={sort} onSort={setSort} />
                <SortHeader label="Client" field="client" sort={sort} onSort={setSort} />
                {maySeeSeats && (
                  <SortHeader label="Seats" field="seats" sort={sort} onSort={setSort} />
                )}
                <th></th>
              </tr>
            </thead>
            <tbody>
              {shown.map((c) => (
                <tr key={c.id}>
                  <td>
                    <span className="named">
                      <Avatar name={c.name} />
                      <Link to={`/companies/${c.id}`}>{c.name}</Link>
                    </span>
                  </td>
                  <td className="muted">{c.industry || "—"}</td>
                  <td>{c.is_client_company
                    ? <Pill kind="ok">client</Pill>
                    : <span className="muted">—</span>}</td>
                  {maySeeSeats && (
                    <td>{c.seat_count === null || c.seats_in_use === undefined
                      ? "—" : `${c.seats_in_use} / ${c.seat_count}`}</td>
                  )}
                  <td className="rowactions">
                    <button className="small" onClick={() => setPeek(c)}
                      aria-label={`Peek at ${c.name}`}>Peek</button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>

      {peek && (
        <Sheet label="Company" onClose={() => setPeek(null)}
          title={<h3 style={{ margin: 0 }}>{peek.name}</h3>}>
          <dl className="facts">
            <dt>Industry</dt><dd>{peek.industry || "—"}</dd>
            <dt>Client</dt>
            <dd>{peek.is_client_company ? "Yes" : "Not a client company"}</dd>
            {maySeeSeats && (
              <>
                <dt>Seats</dt>
                <dd>{peek.seat_count === null || peek.seats_in_use === undefined
                  ? "—" : `${peek.seats_in_use} of ${peek.seat_count} in use`}</dd>
              </>
            )}
            <dt>Email domains</dt>
            <dd>{(peek.domains ?? []).length
              ? (peek.domains ?? []).map((d) => <Pill key={d}>{d}</Pill>)
              : "—"}</dd>
          </dl>
          <Link className="primary button" to={`/companies/${peek.id}`}>
            Open the full record
          </Link>
        </Sheet>
      )}
    </>
  );
}
