import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Modal, PageHead } from "../components/shell";
import { PlaybookEditor } from "../components/Playbooks";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { CenterCard, CenterRow, CentersState, Me, PlaybookRow, api } from "../lib/api";

/** "$50": the Command Centers' prices are whole dollars. */
const whole = (cents: number) => `$${Math.round(cents / 100)}`;

const TIER: Record<string, string> = { fast: "Fast", standard: "Standard", deep: "Deep" };
const PAGE: Record<string, string> = { customers: "Customers", operations: "Operations",
  team: "Team", money: "Money" };

/**
 * Settings → Command Centers (P8): the eight modules, each a discipline at
 * $50 a month, all of them together at most $150. Turning one on only
 * offers its pieces; nothing of a client's changes. The practice library's
 * count, its export and its delete are here too.
 */
export function CommandCentersSettings({ me }: { me: Me }) {
  const qc = useQueryClient();
  const state = useQuery<CentersState>({ queryKey: ["command-centers"],
    queryFn: () => api.get<CentersState>("/api/command-centers/") });
  const [asking, setAsking] = useState<CenterRow | null>(null);
  const [deleting, setDeleting] = useState(false);
  const flip = useMutation({
    mutationFn: ({ code, on }: { code: string; on: boolean }) =>
      api.post<CentersState>(`/api/command-centers/${code}/`, { on }),
    onSuccess: (next) => { qc.setQueryData(["command-centers"], next);
      qc.invalidateQueries({ queryKey: ["me"] }); setAsking(null); },
  });
  const wipe = useMutation({
    mutationFn: () => api.del<CentersState>("/api/command-centers/library/"),
    onSuccess: (next) => { qc.setQueryData(["command-centers"], next); setDeleting(false); },
  });
  const s = state.data;
  const owner = me.role === "FF";
  return (
    <>
      <PageHead title="Command Centers"
        sub="One for each discipline: session templates, a KPI list, playbooks, document templates and AI actions." />
      {state.isError && <Banner kind="bad">{(state.error as Error).message}</Banner>}
      {flip.isError && <Banner kind="bad">{(flip.error as Error).message}</Banner>}
      {s && !s.can_switch && <Banner kind="warn">{s.why_not}</Banner>}
      {s && (
        <>
          <p className="small muted">
            {whole(5000)} a month each, and {whole(s.cap_cents)} a month at most for all of
            them{s.owners_practice ? "; included for your practice" : ""}. Turning one on only
            offers what it brings: your clients' scorecards, templates and goals stay as they
            are, and anything you use is copied into your practice for you to edit.
          </p>
          <div className="center-grid">
            {s.centers.map((c) => (
              <div key={c.code} className={`center-tile${c.on ? " on" : ""}`}>
                <div>
                  <strong>{c.name}</strong>{" "}
                  {c.on ? <Pill kind="ok">On</Pill> : c.status === "available"
                    ? <Pill>Available</Pill> : <Pill kind="warn">{c.next ? "Next" : "Coming"}</Pill>}
                </div>
                <p className="small muted" style={{ margin: 0 }}>{c.description}</p>
                <div className="row tight" style={{ marginTop: "auto" }}>
                  {c.on && <Link className="btn small" to={`/centers/${c.code}`}>Open {c.short_name}</Link>}
                  {owner && c.status === "available" && (
                    <button className={c.on ? "small ghost" : "small primary"}
                      disabled={!s.can_switch || flip.isPending}
                      aria-label={`${c.on ? "Turn off" : "Turn on"} the ${c.name}`}
                      onClick={() => c.on ? flip.mutate({ code: c.code, on: false }) : setAsking(c)}>
                      {c.on ? "Turn off" : "Turn on"}</button>
                  )}
                </div>
              </div>
            ))}
          </div>
          <Card title="Your practice library">
            <p style={{ marginTop: 0 }}>
              <strong>{s.library_count}</strong> record{s.library_count === 1 ? "" : "s"} kept.
            </p>
            <p className="small muted">
              While a Command Center is on, your own notes (never PIN-locked ones), the map rows
              you accept or discard, finished documents and SOPs, and the playbooks you start are
              kept here, for a learning tool that will draft from your own work. Nothing is
              drafted from it yet, and no one else sees it.
            </p>
            {owner && (
              <div className="row tight">
                <a className="btn small" href="/api/command-centers/library/export/">Export</a>
                <button className="small ghost" disabled={s.library_count === 0}
                  onClick={() => setDeleting(true)}>Delete all</button>
              </div>
            )}
          </Card>
        </>
      )}
      {asking && s && (
        <Modal label={`Turn on the ${asking.name}`} title={`Turn on the ${asking.name}?`}
          onClose={() => setAsking(null)}>
          <p style={{ marginTop: 0 }}>{s.price_line}</p>
          <p className="small muted">Nothing changes for your clients. Its pieces are offered
            where you work, and copied into your practice when you first use them.</p>
          <div className="row tight">
            <button className="primary" disabled={flip.isPending}
              onClick={() => flip.mutate({ code: asking.code, on: true })}>Turn it on</button>
            <button className="ghost" onClick={() => setAsking(null)}>Cancel</button>
          </div>
        </Modal>
      )}
      {deleting && (
        <Modal label="Delete the practice library" title="Delete your practice library?"
          onClose={() => setDeleting(false)}>
          <p style={{ marginTop: 0 }}>Every record kept so far is deleted. Your notes,
            documents and playbooks themselves are not touched.</p>
          <div className="row tight">
            <button className="primary" onClick={() => wipe.mutate()}>Delete all</button>
            <button className="ghost" onClick={() => setDeleting(false)}>Cancel</button>
          </div>
        </Modal>
      )}
    </>
  );
}

/** The module card (P8): what a Command Center brings, shelf by shelf. The
 *  navigation names it by its discipline alone ("Operations"). */
export function CommandCenterPage({ me }: { me: Me }) {
  const { code = "" } = useParams();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const card = useQuery<CenterCard>({ queryKey: ["command-center", code],
    queryFn: () => api.get<CenterCard>(`/api/command-centers/${code}/`) });
  const [editing, setEditing] = useState<PlaybookRow | null>(null);
  const template = useMutation({
    mutationFn: (startFrom: string) => api.post<{ id: string }>("/api/strategy-template-builder/",
      { name: `${card.data?.short_name ?? "Operations"} strategy session`, start_from: startFrom }),
    onSuccess: (made) => navigate(`/strategy/templates/${made.id}/build`),
  });
  const open = useMutation({
    mutationFn: (row: PlaybookRow) => row.id ? Promise.resolve(row)
      : api.post<PlaybookRow>("/api/playbooks/copy/", { key: row.key }),
    onSuccess: (row) => { qc.invalidateQueries({ queryKey: ["command-center", code] }); setEditing(row); },
  });
  const c = card.data;
  if (card.isError) return <Banner kind="bad">{(card.error as Error).message}</Banner>;
  if (!c) return <p>Loading…</p>;
  const shelves = c.shelves;
  const editor = me.role === "FF" || me.role === "CF";
  return (
    <>
      <PageHead title={c.name} sub={c.description}
        action={<Link className="btn" to="/plans">Plans</Link>} />
      {!c.on && <Banner kind="warn">This Command Center is off. Turn it on in Settings → Command
        Centers to use what it brings.</Banner>}
      {template.isError && <Banner kind="bad">{(template.error as Error).message}</Banner>}
      {open.isError && <Banner kind="bad">{(open.error as Error).message}</Banner>}
      {!shelves ? <Empty>Coming soon.</Empty> : (
        <>
          <Card title="Session templates">
            <p className="small muted" style={{ marginTop: 0 }}>The strategy session in plain
              words, ready to run, copied into your templates to edit.</p>
            {shelves.session_templates.map((t) => (
              <button key={t.start_from} className="small" disabled={!c.on || me.role !== "FF" || template.isPending}
                onClick={() => template.mutate(t.start_from)}>{t.label}</button>
            ))}
          </Card>
          <Card title="KPI library">
            <p className="small muted" style={{ marginTop: 0 }}>Added on top of the base library,
              offered "From the library" wherever a KPI is made.</p>
            <ul className="shelf">
              {shelves.kpis.map((k) => <li key={k.key}><strong>{k.name}</strong>{" "}
                <span className="small muted">({PAGE[k.page] ?? k.page}) {k.guidance}</span></li>)}
            </ul>
          </Card>
          <Card title="Playbooks">
            <p className="small muted" style={{ marginTop: 0 }}>Start one from a company's page.
              Each arrives as a draft: edit it before its first use.</p>
            <ul className="shelf">
              {shelves.playbooks.map((p) => (
                <li key={p.id ?? p.key}>
                  <strong>{p.name}</strong>{" "}
                  {"is_draft" in p && p.is_draft && <Pill kind="warn">Draft, edit before first use</Pill>}{" "}
                  <span className="small muted">{p.description}</span>{" "}
                  {c.on && editor && (
                    <button className="small ghost" onClick={() => open.mutate(p)}>
                      {p.id ? "Edit" : "Open and edit"}</button>
                  )}
                </li>
              ))}
            </ul>
          </Card>
          <Card title="Document and email templates">
            <ul className="shelf">
              {shelves.documents.map((d) => <li key={d.original}>{d.name} <span className="small muted">
                (Settings → Documents; downloadable as Word)</span></li>)}
              {shelves.emails.map((d) => <li key={d.original}>{d.name} <span className="small muted">
                (Settings → Email templates)</span></li>)}
            </ul>
            {me.role === "FF" && <div className="row tight">
              <Link className="btn small" to="/settings/documents">Documents</Link>
              <Link className="btn small" to="/settings/templates">Email templates</Link>
            </div>}
          </Card>
          <Card title="Tools">
            <p className="small muted" style={{ marginTop: 0 }}>Coming next, with the worksheet engine.</p>
            <ul className="shelf">{shelves.tools.map((t) => <li key={t}>{t}</li>)}</ul>
          </Card>
          <Card title="Integrations">
            <p className="small muted" style={{ marginTop: 0 }}>Recommended, and shown first in a
              company's feed picker.</p>
            <ul className="shelf">{shelves.feeds.map((f) => <li key={f.code}>{f.name}</li>)}</ul>
          </Card>
          <Card title="AI actions">
            <ul className="shelf">{shelves.ai_actions.map((a) => <li key={a.key}>{a.label}{" "}
              <span className="small muted">({TIER[a.tier] ?? a.tier})</span></li>)}</ul>
            <p className="small muted">They run in your connected AI app, and what they make
              waits where you approve it. {me.role === "FF" && <Link to="/ai-usage">Settings → AI</Link>}</p>
          </Card>
        </>
      )}
      {editing && <PlaybookEditor playbook={editing} onClose={() => setEditing(null)} />}
    </>
  );
}
