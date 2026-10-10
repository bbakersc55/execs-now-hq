import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { Banner, Card } from "./ui";

interface Item { key: string; label: string; to: string; done: boolean }
interface CardChoice { hidden: boolean; never: boolean; hidden_until: string | null }

function useItems(enabled = true) {
  return useQuery<Item[]>({
    queryKey: ["getting-started"], queryFn: () => api.get<Item[]>("/api/getting-started"),
    enabled });
}

/** P2: the practice owner's Getting started list. Each item is worked out
 *  from the practice's own data, so it ticks itself; the card goes away when
 *  every item is done.
 *
 *  It can also be put away (owner, 2026-10-10), by the person and for that
 *  person only: "Hide for now" brings it back tomorrow, "Don't show again"
 *  does not. Either way, what is still undone stays at the top of Settings
 *  (`SetupStillToDo`). */
export function GettingStarted() {
  const qc = useQueryClient();
  const { data } = useItems();
  const choice = useQuery<CardChoice>({
    queryKey: ["getting-started-card"],
    queryFn: () => api.get<CardChoice>("/api/getting-started/card") });
  const dismiss = useMutation({
    mutationFn: (how: "later" | "never") =>
      api.post<CardChoice>("/api/getting-started/card", { how }),
    onSuccess: (now) => qc.setQueryData(["getting-started-card"], now) });
  if (!data || data.every((i) => i.done)) return null;
  // Not drawn until the person's choice is known, so a card they put away
  // does not flash up first.
  if (!choice.data || choice.data.hidden) return null;
  const left = data.filter((i) => !i.done).length;
  return (
    <Card title={`Getting started · ${data.length - left} of ${data.length} done`}
      actions={<span className="row tight">
        <button className="ghost small" disabled={dismiss.isPending}
          onClick={() => dismiss.mutate("later")}>Hide for now</button>
        <button className="ghost small" disabled={dismiss.isPending}
          onClick={() => dismiss.mutate("never")}>Don't show again</button>
      </span>}>
      <ul aria-label="Getting started" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {data.map((i) => (
          <li key={i.key} style={{ padding: "0.3rem 0" }}>
            <span aria-hidden="true" style={{ display: "inline-block", width: "1.4rem" }}>
              {i.done ? "✓" : "○"}</span>
            {i.done ? <span className="muted">{i.label}</span>
              : <Link to={i.to}>{i.label}</Link>}
          </li>
        ))}
      </ul>
      <p className="tiny muted" style={{ margin: "var(--s2) 0 0" }}>
        Hidden or not, what is left stays listed at the top of Settings until it is done.
      </p>
    </Card>
  );
}

/** The top of Settings, for the practice owner: every checklist item still
 *  undone, linked, until it is done. The card's two dismissals do not reach
 *  it: a practice with no Gmail connected should not be able to forget. */
export function SetupStillToDo() {
  const { data } = useItems();
  const left = (data ?? []).filter((i) => !i.done);
  if (left.length === 0) return null;
  return (
    <div role="region" aria-label="Setup still to do">
      <Banner kind="warn">
        <strong>Setup still to do:</strong>{" "}
        {left.map((i, index) => (
          <span key={i.key}>{index > 0 && " · "}<Link to={i.to}>{i.label}</Link></span>
        ))}
      </Banner>
    </div>
  );
}
