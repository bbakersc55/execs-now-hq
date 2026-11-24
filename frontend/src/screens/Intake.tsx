/** Owner intake: a company's intakes, and starting one (docs/p14_intake_forms.md).
 *  For the practice owner and a client company's managers and above. */
import { useMutation, useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { Banner, Card, Empty, Field, Pill, when } from "../components/ui";
import type { Me } from "../lib/api";
import { intake, STATUS_KIND } from "../lib/intake";

export function IntakeScreen({ me }: { me: Me }) {
  const [params, setParams] = useSearchParams();
  const navigate = useNavigate();
  const { data: companies } = useQuery({ queryKey: ["intake-companies"],
                                          queryFn: intake.companies });
  const list = companies?.companies ?? [];
  const company = params.get("company") || list[0]?.id || "";
  const { data, isLoading } = useQuery({
    queryKey: ["intake-list", company], queryFn: () => intake.submissions(company),
    enabled: !!company,
  });
  const [first, setFirst] = useState("");
  const [last, setLast] = useState("");
  const [email, setEmail] = useState("");
  const start = useMutation({
    mutationFn: () => intake.start(company, { first_name: first, last_name: last, email }),
    onSuccess: (r) => navigate(`/intake/${r.id}`),
  });
  if (companies && !list.length) {
    return <div className="page"><h1>Owner intake</h1>
      <Empty>Owner intake isn't switched on for any company you run.</Empty></div>;
  }
  const name = list.find((c) => c.id === company)?.name ?? "";
  return (
    <div className="page">
      <div className="spread">
        <h1 style={{ margin: 0 }}>Owner intake{name && list.length > 1 ? `: ${name}` : ""}</h1>
        {company && <Link className="btn ghost" to={`/intake/settings/${company}`}>
          Form settings</Link>}
      </div>
      {list.length > 1 && (
        <div className="row" style={{ gap: ".5rem", margin: ".75rem 0" }}>
          {list.map((c) => (
            <button key={c.id} type="button" className={c.id === company ? "primary small"
              : "ghost small"} onClick={() => setParams({ company: c.id })}>{c.name}</button>
          ))}
        </div>
      )}
      {data?.test_mode && <Banner kind="warn"><strong>Test mode is on.</strong> Send to Track
        checks everything and writes nothing. Turn it off in Form settings.</Banner>}
      <Card title="Start an intake for a new owner">
        <p className="muted" style={{ marginTop: 0 }}>Makes the owner's personal link. Copy it,
          or open it in your own email; the app never emails owners. You can also fill the whole
          form in yourself, on the owner's behalf.</p>
        <form className="row wrap" style={{ gap: ".75rem", alignItems: "flex-end" }}
          onSubmit={(e) => { e.preventDefault(); start.mutate(); }}>
          <Field label="First name"><input value={first}
            onChange={(e) => setFirst(e.target.value)} required /></Field>
          <Field label="Last name"><input value={last}
            onChange={(e) => setLast(e.target.value)} /></Field>
          <Field label="Email"><input type="email" value={email}
            onChange={(e) => setEmail(e.target.value)} /></Field>
          <button className="primary" type="submit" disabled={!first.trim() || start.isPending}>
            {start.isPending ? "Starting…" : "Start intake"}</button>
        </form>
        {start.isError && <Banner kind="warn">{(start.error as Error).message}</Banner>}
      </Card>
      <Card title="Intakes">
        {isLoading ? <p className="muted">Loading…</p> : !data?.submissions.length ? (
          <Empty>No intakes yet.</Empty>
        ) : (
          <table className="table">
            <thead><tr><th>#</th><th>Owner</th><th>Property</th><th>Status</th><th>Link</th>
              <th>Started</th></tr></thead>
            <tbody>
              {data.submissions.map((s) => (
                <tr key={s.id} className="clickable" onClick={() => navigate(`/intake/${s.id}`)}>
                  <td><Link to={`/intake/${s.id}`}>#{s.number}</Link></td>
                  <td>{s.owner}</td>
                  <td>{s.property || <span className="muted">Not given yet</span>}</td>
                  <td><Pill kind={STATUS_KIND[s.status] === "danger" ? "bad"
                    : STATUS_KIND[s.status] ?? ""}>{s.status_label}</Pill>
                    {s.tested && <> <Pill kind="warn">Test</Pill></>}</td>
                  <td>{s.status === "sent" || s.status === "discarded" ? "—"
                    : s.link_open ? "Open" : <Pill kind="warn">Expired</Pill>}</td>
                  <td className="when">{when(s.created_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
      {me.role === "FF" && <p className="muted small">Who sees intakes: you, and everyone ticked
        for Owner intake in the company's Owner agreement settings, People and permissions.</p>}
    </div>
  );
}
