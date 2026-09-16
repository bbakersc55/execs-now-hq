import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { useNavigate } from "react-router-dom";

import { ActAsCandidate, Me, api } from "../lib/api";
import { Banner } from "./ui";

const ROLE_WORD: Record<string, string> = { FCC: "founder", ECC: "employee" };

/**
 * FR-3.42 — acting as another user.
 *
 * Starting or stopping changes who the whole app is talking to, so every
 * cached answer is reset rather than trusted, and the app lands somewhere that
 * makes sense for the identity it now has.
 */
function useIdentityChange() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  return async (to: string) => {
    await qc.resetQueries();
    navigate(to);
  };
}

export function useStartActing() {
  const change = useIdentityChange();
  return useMutation({
    mutationFn: (membership: string) => api.post("/api/act-as/", { membership }),
    onSuccess: () => change("/work"),
  });
}

/** Persistent while acting: names both people, and is the only way out. */
export function ActingBanner({ me }: { me: Me }) {
  const change = useIdentityChange();
  const [error, setError] = useState("");
  const stop = useMutation({
    mutationFn: () => api.post<{ return_to: string }>("/api/act-as/stop/"),
    onSuccess: (r) => change(r.return_to),
    onError: (e: Error) => setError(e.message),
  });
  const a = me.acting;
  if (!a) return null;

  return (
    <div role="status" aria-label="Acting as" style={{ position: "sticky", top: 0, zIndex: 5 }}>
      <Banner kind="warn">
        <strong>{a.real_name} is acting as {a.as_name}</strong> ({ROLE_WORD[a.as_role] ?? a.as_role}
        {a.company_name && `, ${a.company_name}`}). Everything done here is recorded as done by
        {" "}{a.real_name} on behalf of {a.as_name}, and <strong>no email is sent</strong>.{" "}
        <button className="primary" disabled={stop.isPending} onClick={() => stop.mutate()}>
          Stop acting as {a.as_name}
        </button>
        {error && <div>{error}</div>}
      </Banner>
    </div>
  );
}

/**
 * The practice's entry point: a company's portal-access list, and a contact
 * page for a contact who already has access.
 *
 * "View portal as" rather than "Act as", because that is what it is for — the
 * practice has no other way to see the client's own screens, the activity log
 * (FR-3.41) among them, which no staff role can open from their own sidebar.
 */
export function ActAsButton({ membership, name }: { membership: string; name: string }) {
  const start = useStartActing();
  return (
    <button className="ghost small" disabled={start.isPending}
      aria-label={`View portal as ${name}`}
      onClick={() => {
        if (confirm(`View the portal as ${name}? You will see and do exactly what they can. `
                    + `Everything is `
                    + "recorded as done by you on their behalf, and no email is sent until you stop.")) {
          start.mutate(membership);
        }
      }}>
      View portal as…
    </button>
  );
}

/** A founder user's entry point: anyone else at their own company. */
export function ActAsColleague({ me }: { me: Me }) {
  const [picked, setPicked] = useState("");
  const start = useStartActing();
  const candidates = useQuery<ActAsCandidate[]>({
    queryKey: ["act-as-candidates"],
    queryFn: () => api.get<ActAsCandidate[]>("/api/act-as/candidates/"),
    enabled: me.role === "FCC" && !me.acting,
  });
  if (me.role !== "FCC" || me.acting || !(candidates.data ?? []).length) return null;

  return (
    <div className="small" style={{ marginTop: ".6rem" }}>
      <select aria-label="Act as a colleague" value={picked}
        onChange={(e) => setPicked(e.target.value)}>
        <option value="">Act as a colleague…</option>
        {candidates.data!.map((c) => (
          <option key={c.membership} value={c.membership}>{c.name}</option>
        ))}
      </select>
      <button className="ghost small" disabled={!picked || start.isPending}
        onClick={() => start.mutate(picked)}>Act as</button>
    </div>
  );
}
