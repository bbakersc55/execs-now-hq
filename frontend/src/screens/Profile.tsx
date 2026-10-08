import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PageHead } from "../components/shell";
import { Banner, Card, Field } from "../components/ui";
import { api } from "../lib/api";

export interface ProfileData {
  email: string;
  full_name: string;
  role_label: string | null;
  practice: string | null;
  client_company_name: string | null;
  /** False while acting as this person: their profile is theirs to change. */
  editable: boolean;
}

/**
 * Profile (UI 3 spec §5): the person's own name, and where they sit. For
 * every signed-in person, client users included. The sign-in email is shown
 * and cannot be changed here (D6).
 */
export function Profile() {
  const qc = useQueryClient();
  const profile = useQuery<ProfileData>({
    queryKey: ["profile"], queryFn: () => api.get<ProfileData>("/api/me/profile"),
  });
  const [name, setName] = useState("");
  const [saved, setSaved] = useState(false);
  useEffect(() => { if (profile.data) setName(profile.data.full_name); }, [profile.data]);

  const save = useMutation({
    mutationFn: () => api.patch<ProfileData>("/api/me/profile", { full_name: name }),
    onSuccess: (data) => {
      qc.setQueryData(["profile"], data);
      // The top bar, and anywhere else that names the person signed in.
      qc.invalidateQueries({ queryKey: ["me"] });
      setSaved(true);
    },
  });

  if (profile.isLoading) return <p className="muted">Loading…</p>;
  if (profile.isError || !profile.data) {
    return <Banner kind="bad">Your profile could not be loaded. Reload the page to try again.</Banner>;
  }
  const p = profile.data;
  const changed = name.trim() !== p.full_name && name.trim() !== "";

  return (
    <div className="record">
      <PageHead title="Profile" sub="Your name as it appears to the people you work with." />
      {!p.editable && (
        <Banner kind="warn">
          You are acting as {p.full_name || p.email}. Their profile is theirs to change, so
          it is shown here and cannot be edited.
        </Banner>
      )}
      <Card title="Your details">
        <form onSubmit={(e) => { e.preventDefault(); if (changed) save.mutate(); }}>
          <Field label="Full name">
            <input aria-label="Full name" value={name} maxLength={200} disabled={!p.editable}
              onChange={(e) => { setName(e.target.value); setSaved(false); }}
              style={{ maxWidth: "28rem" }} />
          </Field>
          {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
          {saved && <Banner kind="ok">Saved.</Banner>}
          {p.editable && (
            <button className="primary" type="submit" disabled={!changed || save.isPending}>
              {save.isPending ? "Saving…" : "Save"}
            </button>
          )}
        </form>
      </Card>
      <Card title="Your account">
        <dl className="facts">
          <dt>Sign-in email</dt>
          <dd>
            {p.email}
            <div className="small muted">
              This is how you sign in, so it cannot be changed here. Ask the practice owner.
            </div>
          </dd>
          {p.role_label && <><dt>Role</dt><dd>{p.role_label}</dd></>}
          {p.practice && <><dt>Practice</dt><dd>{p.practice}</dd></>}
          {p.client_company_name && <><dt>Company</dt><dd>{p.client_company_name}</dd></>}
        </dl>
      </Card>
    </div>
  );
}
