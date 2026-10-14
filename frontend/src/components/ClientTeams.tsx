import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import {
  ClientTeamArchivePreview, ClientTeamName, ClientTeams, Company, Me, api,
} from "../lib/api";
import {
  LEVEL_CODES, LEVEL_LABEL, MAY_CREATE_CODES, MAY_CREATE_LABEL, roleLabel,
} from "../lib/roles";
import { usePracticeName } from "../lib/branding";
import { Banner, Card, Field } from "./ui";

const MANAGES = ["FF", "CF"];

/** A client company's teams, for a picker. Asked only once a company is
 *  chosen: the practice's own work is on no team. */
export function useTeamNames(company: string) {
  return useQuery<ClientTeamName[]>({
    queryKey: ["client-team-names", company],
    queryFn: () => api.get<ClientTeamName[]>(`/api/client-teams/names/?company=${company}`),
    enabled: !!company,
    retry: false,
  });
}

/**
 * The Team a client's project, or a task in no project, is on (P7 §1.2).
 *
 * `value` "" is the company's default team, which is where the server puts
 * work that names none. With no company there is nothing to choose, and with
 * one team there is nothing to choose between, so the field is not drawn.
 */
export function TeamField({ company, value, onChange, label }: {
  company: string; value: string; onChange: (team: string) => void; label: string;
}) {
  const teams = useTeamNames(company);
  const rows = teams.data ?? [];
  if (!company || rows.length < 2) return null;
  const home = rows.find((t) => t.is_default);
  return (
    <Field label="Team">
      <select aria-label={label} value={value || home?.id || ""}
        onChange={(e) => onChange(e.target.value)}>
        {rows.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
      </select>
    </Field>
  );
}

/**
 * Narrowing Work and Tasks to one team, beside the filter by client (§4.1).
 *
 * A team is a client company's, so there is one to choose only once a single
 * client is chosen, and only when that client has more than its default
 * team. `useTeamFilter` forgets a team that is not the chosen client's.
 */
export function useTeamFilter(company: string) {
  const [chosen, choose] = useState("");
  const real = company && company !== "internal" ? company : "";
  const teams = useTeamNames(real);
  const rows = teams.data ?? [];
  return { teams: rows, choose,
           team: rows.some((t) => t.id === chosen) ? chosen : "" };
}

export function TeamFilter({ teams, value, onChange }: {
  teams: ClientTeamName[]; value: string; onChange: (team: string) => void;
}) {
  if (teams.length < 2) return null;
  return (
    <select aria-label="Filter by team" value={value}
      style={{ width: "auto", minWidth: 150 }} onChange={(e) => onChange(e.target.value)}>
      <option value="">All teams</option>
      {teams.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
    </select>
  );
}

/** The three choices an invitation carries (P7-9): the team, the level on
 *  it, and what the person may create. They start at the default team,
 *  Member, and projects and tasks. */
export type Placement = { team: string; level: string; may_create: string };
export const START: Placement = { team: "", level: "member", may_create: "projects" };

export function PlacementFields({ company, name, value, onChange }: {
  company: string; name: string; value: Placement; onChange: (next: Placement) => void;
}) {
  const teams = useTeamNames(company);
  const rows = teams.data ?? [];
  return (
    <>
      {rows.length > 1 && (
        <select aria-label={`Team for ${name}`}
          value={value.team || rows.find((t) => t.is_default)?.id || ""}
          onChange={(e) => onChange({ ...value, team: e.target.value })}>
          {rows.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
        </select>
      )}{" "}
      <select aria-label={`Level for ${name}`} value={value.level}
        onChange={(e) => onChange({ ...value, level: e.target.value })}>
        {LEVEL_CODES.map((code) => <option key={code} value={code}>{LEVEL_LABEL[code]}</option>)}
      </select>{" "}
      <select aria-label={`What ${name} may create`} value={value.may_create}
        onChange={(e) => onChange({ ...value, may_create: e.target.value })}>
        {MAY_CREATE_CODES.map((code) => (
          <option key={code} value={code}>May create: {MAY_CREATE_LABEL[code].toLowerCase()}</option>
        ))}
      </select>
    </>
  );
}

/** What a placement sends with a grant: only what was chosen. */
export const placementBody = (value: Placement) => ({
  ...(value.team ? { team: value.team } : {}),
  level: value.level, may_create: value.may_create,
});

/** The practice, by name, in the portal's words. Asked only where shown. */
function PracticeName() {
  return <>{usePracticeName()}</>;
}

/**
 * P7 phases 2 and 3 — a client company's teams, set up by the practice, or by
 * the client owner in the portal ("Your team").
 *
 * Teams first: each with what it holds and who is on it. Then the people:
 * for each, their level on every team, whether they are senior leadership
 * of all of them, and what they may create. Every control saves as it is
 * changed and the card is redrawn from the server's answer, so what is shown
 * is what is held. A level takes effect the moment it is set.
 *
 * The practice owner, and an associate on a company they are assigned. An
 * assistant is not shown the card. The client owner, for their own company:
 * a client owner's settings are left to the practice, and nobody is given
 * more to create than the client owner may create (the server says so too).
 */
export function ClientTeamsCard({ me, company }: {
  me: Me; company: Pick<Company, "id" | "is_client_company">;
}) {
  const qc = useQueryClient();
  const [name, setName] = useState("");
  const [renaming, setRenaming] = useState<{ id: string; name: string } | null>(null);
  const [message, setMessage] = useState<{ kind: string; text: string } | null>(null);
  const key = ["client-teams", company.id];
  const portal = me.role === "FCC";
  const mayManage = portal ? company.id === me.client_company
    : !!me.role && MANAGES.includes(me.role) && company.is_client_company;

  const card = useQuery<ClientTeams>({
    queryKey: key,
    queryFn: () => api.get<ClientTeams>(`/api/client-teams/?company=${company.id}`),
    enabled: mayManage,
    retry: false,
  });

  const took = (data: ClientTeams, text = "") => {
    qc.setQueryData(key, data);
    qc.invalidateQueries({ queryKey: ["client-team-names", company.id] });
    qc.invalidateQueries({ queryKey: ["portal-access", company.id] });
    setMessage(text ? { kind: "ok", text } : null);
  };
  const failed = (e: Error) => setMessage({ kind: "bad", text: e.message });

  const add = useMutation({
    mutationFn: () => api.post<ClientTeams>("/api/client-teams/",
                                            { company: company.id, name: name.trim() }),
    onSuccess: (data) => { took(data, `“${name.trim()}” added.`); setName(""); },
    onError: failed,
  });
  const rename = useMutation({
    mutationFn: (team: { id: string; name: string }) =>
      api.patch<ClientTeams>(`/api/client-teams/${team.id}/`, { name: team.name.trim() }),
    onSuccess: (data) => { took(data); setRenaming(null); },
    onError: failed,
  });
  const archive = useMutation({
    mutationFn: (id: string) => api.post<ClientTeams>(`/api/client-teams/${id}/archive/`, {}),
    onSuccess: (data) => {
      const moved = data.archived;
      took(data, moved
        ? `Archived. ${moved.projects} project(s), ${moved.tasks} task(s) and `
          + `${moved.people_moved} person(s) moved to ${moved.moved_to}. Nothing was deleted.`
        : "Archived.");
      qc.invalidateQueries({ queryKey: ["projects"] });
      qc.invalidateQueries({ queryKey: ["tasks"] });
    },
    onError: failed,
  });
  const level = useMutation({
    mutationFn: (to: { team: string; membership: string; level: string }) =>
      api.post<ClientTeams>(`/api/client-teams/${to.team}/level/`,
                            { membership: to.membership, level: to.level || null }),
    onSuccess: (data) => took(data),
    onError: failed,
  });
  const person = useMutation({
    mutationFn: (to: { membership: string; may_create?: string; leads_all_teams?: boolean }) =>
      api.post<ClientTeams>("/api/client-teams/person/", to),
    onSuccess: (data) => took(data),
    onError: failed,
  });

  if (!mayManage || !card.data) return null;
  const data = card.data;
  const busy = level.isPending || person.isPending;
  // The client owner gives nobody more to create than they may themselves.
  const ceiling = portal
    ? MAY_CREATE_CODES.indexOf((data.people.find((p) => p.role === "FCC"
        && p.email === me.email)?.may_create ?? "nothing") as typeof MAY_CREATE_CODES[number])
    : MAY_CREATE_CODES.length - 1;

  // Archiving says what will move before it is confirmed.
  const askToArchive = async (team: ClientTeams["teams"][number]) => {
    try {
      const p = await api.get<ClientTeamArchivePreview>(`/api/client-teams/${team.id}/archive/`);
      const people = p.people_left_on_no_team
        ? ` ${p.people_left_on_no_team} of its ${p.people} people are on no other team and `
          + `join ${p.moves_to} at the level they hold now.`
        : "";
      if (confirm(`Archive ${team.name}? Its ${p.projects} project(s) and ${p.tasks} task(s) `
                  + `in no project move to ${p.moves_to}.${people} Nothing is deleted, and `
                  + "everyone keeps their sign-in.")) {
        archive.mutate(team.id);
      }
    } catch (e) {
      failed(e as Error);
    }
  };

  return (
    <Card title="Teams">
      {message && <Banner kind={message.kind}>{message.text}</Banner>}
      <p className="small muted" style={{ marginTop: 0 }}>
        A member sees their own work; a manager, their team's and the other teams' read-only;
        senior leadership edits goals too; a viewer looks and changes nothing. A change here
        takes effect at once.{" "}
        {portal
          ? <>To check what someone sees, use “Act as a colleague” in your account menu.
              A client owner’s own settings are set by <PracticeName />.</>
          : <>To check what someone sees, use “See the portal as” beside their name above.</>}
      </p>
      <table aria-label="Teams">
        <thead><tr><th>Team</th><th>Holds</th><th>People</th><th></th></tr></thead>
        <tbody>
          {data.teams.map((team) => (
            <tr key={team.id}>
              <td>
                {renaming?.id === team.id ? (
                  <form onSubmit={(e) => { e.preventDefault(); rename.mutate(renaming); }}>
                    <input aria-label={`New name for ${team.name}`} value={renaming.name}
                      onChange={(e) => setRenaming({ ...renaming, name: e.target.value })} />{" "}
                    <button className="small primary" type="submit"
                      disabled={!renaming.name.trim() || rename.isPending}>Save</button>{" "}
                    <button className="ghost small" type="button"
                      onClick={() => setRenaming(null)}>Cancel</button>
                  </form>
                ) : (
                  <>{team.name}{team.is_default && <span className="muted"> · the default</span>}</>
                )}
              </td>
              <td className="small">{team.projects} project{team.projects === 1 ? "" : "s"},{" "}
                {team.open_tasks} open task{team.open_tasks === 1 ? "" : "s"}</td>
              <td className="small">{team.people.length}</td>
              <td>
                <button className="ghost small" aria-label={`Rename ${team.name}`}
                  onClick={() => setRenaming({ id: team.id, name: team.name })}>Rename</button>{" "}
                {!team.is_default && (
                  <button className="ghost small" aria-label={`Archive ${team.name}`}
                    disabled={archive.isPending} onClick={() => askToArchive(team)}>
                    Archive…</button>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <form className="row" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
        <input aria-label="Name of the new team" placeholder="Operations, Sales, Front office…"
          value={name} maxLength={80} onChange={(e) => setName(e.target.value)} />
        <button type="submit" disabled={!name.trim() || add.isPending}>Add a team</button>
      </form>

      {data.people.length > 0 && (
        <table aria-label="People and their levels" style={{ marginTop: "var(--s3)" }}>
          <thead>
            <tr>
              <th>Person</th>
              {data.teams.map((team) => <th key={team.id}>{team.name}</th>)}
              <th>Every team</th>
              <th>May create</th>
            </tr>
          </thead>
          <tbody>
            {data.people.map((p) => {
              const owner = p.role === "FCC";
              return (
                <tr key={p.id}>
                  <td>{p.name}<div className="when">{p.email}</div></td>
                  {owner ? (
                    <td colSpan={data.teams.length + 1} className="small muted">
                      {roleLabel("FCC")}: everything, in every team.
                    </td>
                  ) : (
                    <>
                      {data.teams.map((team) => (
                        <td key={team.id}>
                          <select aria-label={`${p.name} on ${team.name}`} disabled={busy}
                            value={p.teams.find((t) => t.team === team.id)?.level ?? ""}
                            onChange={(e) => level.mutate({ team: team.id, membership: p.id,
                                                            level: e.target.value })}>
                            <option value="">Not on it</option>
                            {LEVEL_CODES.map((code) => (
                              <option key={code} value={code}>{LEVEL_LABEL[code]}</option>
                            ))}
                          </select>
                        </td>
                      ))}
                      <td>
                        <label className="small inline">
                          <input type="checkbox" checked={p.leads_all_teams} disabled={busy}
                            aria-label={`${p.name} is senior leadership of every team`}
                            onChange={(e) => person.mutate({ membership: p.id,
                                                             leads_all_teams: e.target.checked })} />
                          {" "}{LEVEL_LABEL.leader}
                        </label>
                      </td>
                    </>
                  )}
                  <td>
                    {portal && owner ? (
                      <span className="small">{MAY_CREATE_LABEL[p.may_create]}
                        <span className="muted"> · set by <PracticeName /></span></span>
                    ) : (
                      <select aria-label={`What ${p.name} may create`} value={p.may_create}
                        disabled={busy}
                        onChange={(e) => person.mutate({ membership: p.id,
                                                         may_create: e.target.value })}>
                        {MAY_CREATE_CODES.map((code, i) => (
                          <option key={code} value={code}
                            disabled={i > ceiling && code !== p.may_create}>
                            {MAY_CREATE_LABEL[code]}</option>
                        ))}
                      </select>
                    )}
                    {!owner && p.teams.length === 0 && !p.leads_all_teams && (
                      <div className="small muted">On no team: sees only work that is theirs.</div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </Card>
  );
}
