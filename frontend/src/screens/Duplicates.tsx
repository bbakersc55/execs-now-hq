import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PageHead } from "../components/shell";
import { Banner, Card, Empty, Pill } from "../components/ui";
import { DuplicateGroup, DuplicateMember, api } from "../lib/api";

/**
 * Merge duplicates (owner, 2026-09-29): likely duplicate groups across the
 * whole book — the same email address, or the same full name — each with a
 * survivor to choose and one click to merge the rest into it. It uses the same
 * merge as the two-record screen: every email, phone, note, task, meeting and
 * unsubscribe moves to the survivor. FF and VA only (matrix 4.5).
 */
export function Duplicates() {
  const groups = useQuery<DuplicateGroup[]>({
    queryKey: ["duplicate-groups"],
    queryFn: () => api.get("/api/contacts/duplicate-groups/"),
  });
  const qc = useQueryClient();
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  // The last "Not duplicates", so it can be taken back from the banner.
  const [dismissed, setDismissed] = useState<{ ids: string[]; name: string } | null>(null);
  const list = groups.data ?? [];

  const undo = useMutation({
    mutationFn: (ids: string[]) =>
      api.post("/api/contacts/not-duplicates/", { contacts: ids, undo: true }),
    onSuccess: () => {
      setDismissed(null);
      setNote("Undone: they are back in the list.");
      qc.invalidateQueries({ queryKey: ["duplicate-groups"] });
    },
    onError: (e: Error) => setProblem(e.message),
  });

  return (
    <>
      <PageHead title="Merge duplicates" crumbs={[{ to: "/contacts", label: "Contacts" }]}
        sub="Contacts that share an email address or a full name. Choose who stays; the others merge into them." />
      {note && <Banner kind="ok">{note}</Banner>}
      {dismissed && (
        <Banner kind="ok">
          Marked {dismissed.name} as not duplicates. They won't be suggested together again.{" "}
          <button className="ghost small" disabled={undo.isPending}
            onClick={() => undo.mutate(dismissed.ids)}>Undo</button>
        </Banner>
      )}
      {problem && <Banner kind="bad">{problem}</Banner>}
      {groups.isError && <Banner kind="bad">{(groups.error as Error).message}</Banner>}
      {groups.isLoading ? <p>Loading…</p> : list.length === 0 ? (
        <Empty>No likely duplicates. Contacts known only by a first name are not compared by name.</Empty>
      ) : (
        <>
          <p className="small muted">{list.length} group{list.length === 1 ? "" : "s"}.</p>
          {list.map((group) => (
            <Group key={group.key} group={group} setNote={setNote} setProblem={setProblem}
              onDismissed={(ids, name) => { setNote(""); setDismissed({ ids, name }); }} />
          ))}
        </>
      )}
    </>
  );
}

function Group({ group, setNote, setProblem, onDismissed }: {
  group: DuplicateGroup; setNote: (t: string) => void; setProblem: (t: string) => void;
  onDismissed: (ids: string[], name: string) => void;
}) {
  const qc = useQueryClient();
  const [survivor, setSurvivor] = useState(group.suggested_survivor);
  const keep = group.contacts.find((c) => c.id === survivor)!;
  const others = group.contacts.filter((c) => c.id !== survivor);

  const merge = useMutation({
    mutationFn: () => api.post("/api/contacts/merge-group/", {
      survivor, absorbed: others.map((c) => c.id),
    }),
    onSuccess: () => {
      setProblem("");
      setNote(`Merged ${others.length} into ${keep.name}.`);
      qc.invalidateQueries({ queryKey: ["duplicate-groups"] });
      qc.invalidateQueries({ queryKey: ["contacts"] });
    },
    onError: (e: Error) => setProblem(e.message),
  });

  const notDuplicates = useMutation({
    mutationFn: () => api.post("/api/contacts/not-duplicates/", {
      contacts: group.contacts.map((c) => c.id),
    }),
    onSuccess: () => {
      setProblem("");
      onDismissed(group.contacts.map((c) => c.id),
        group.contacts.length === 2 ? `these two ${group.contacts[0].name}s`
          : `these ${group.contacts.length} contacts`);
      qc.invalidateQueries({ queryKey: ["duplicate-groups"] });
    },
    onError: (e: Error) => setProblem(e.message),
  });
  const nameOf = (id: string) => group.contacts.find((c) => c.id === id)?.name ?? "";
  const shortOf = (id: string) => summary(group.contacts.find((c) => c.id === id)!)
    .split(" · ").slice(0, 2).join(", ");

  return (
    <Card title={group.contacts[0].name}
      actions={group.reasons.map((r) => <Pill key={r}>{r}</Pill>)}>
      {group.dismissed_pairs.length > 0 && (
        <p className="small muted" style={{ marginTop: 0 }}>
          {group.dismissed_pairs.map(([a, b]) => `${nameOf(a)} (${shortOf(a)}) and `
            + `${nameOf(b)} (${shortOf(b)})`).join("; ")} were already marked not
          duplicates. They're here again because a newer contact matches them.
        </p>
      )}
      <fieldset className="choices">
        <legend className="small muted">Who stays</legend>
        {group.contacts.map((c) => (
          <label key={c.id} className="choice">
            <input type="radio" name={`survivor-${group.key}`} checked={survivor === c.id}
              onChange={() => setSurvivor(c.id)} />
            <span>
              <Link to={`/contacts/${c.id}`}>{c.name}</Link>
              <span className="small muted"> · {summary(c)}</span>
            </span>
          </label>
        ))}
      </fieldset>
      <div className="row tight">
        <button className="primary small" disabled={merge.isPending}
          aria-label={`Merge into ${keep.name} (${group.key})`}
          onClick={() => merge.mutate()}>
          Merge {others.length} into {keep.name}
        </button>
        <button className="ghost small" disabled={notDuplicates.isPending}
          aria-label={`Not duplicates (${group.key})`}
          onClick={() => notDuplicates.mutate()}>
          Not duplicates
        </button>
        {group.contacts.length === 2 && (
          <Link className="small" to={`/merge/${keep.id}/${others[0].id}`}>
            Compare field by field instead
          </Link>
        )}
      </div>
    </Card>
  );
}

function summary(c: DuplicateMember): string {
  return [
    c.company || "no company",
    c.emails[0] || "no email",
    c.last_meeting ? `last met ${c.last_meeting}` : "no meetings",
    `${c.tasks} task${c.tasks === 1 ? "" : "s"}, ${c.notes} note${c.notes === 1 ? "" : "s"}`,
    `added ${c.created_at.slice(0, 10)}`,
  ].join(" · ");
}
