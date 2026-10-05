import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";

import { PictureCrop } from "../components/PictureCrop";
import { Avatar, PageHead } from "../components/shell";
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
  picture_url: string | null;
  /** False in the Practices area, where no practice holds the picture. */
  can_have_picture: boolean;
}

const PICTURE_TYPES = ["image/jpeg", "image/png", "image/webp"];
const PICTURE_MAX = 5 * 1024 * 1024;

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
    <>
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
      {p.can_have_picture && <Picture profile={p} />}
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
    </>
  );
}

/**
 * The profile picture (UI 3 spec §6): choose a file, crop it square, and what
 * the server keeps is a small JPEG it made itself. Shown in the top bar.
 */
function Picture({ profile }: { profile: ProfileData }) {
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [problem, setProblem] = useState("");

  const done = (data: ProfileData) => {
    qc.setQueryData(["profile"], data);
    qc.invalidateQueries({ queryKey: ["me"] });
    setFile(null);
    setProblem("");
  };
  const upload = useMutation({
    mutationFn: (picture: Blob) => {
      const body = new FormData();
      body.append("picture", picture, "picture.jpg");
      return api.post<ProfileData>("/api/me/profile/picture", body);
    },
    onSuccess: done,
    onError: (e: Error) => { setFile(null); setProblem(e.message); },
  });
  const remove = useMutation({
    mutationFn: () => api.del<ProfileData>("/api/me/profile/picture"),
    onSuccess: done,
    onError: (e: Error) => setProblem(e.message),
  });

  function choose(chosen: File | undefined) {
    if (!chosen) return;
    if (!PICTURE_TYPES.includes(chosen.type)) {
      setProblem("Use a JPEG, PNG or WebP picture.");
    } else if (chosen.size > PICTURE_MAX) {
      setProblem(`That picture is ${(chosen.size / 1024 / 1024).toFixed(1)} MB; the limit is 5 MB.`);
    } else {
      setProblem("");
      setFile(chosen);
    }
  }

  return (
    <Card title="Your picture">
      <div className="profile-picture">
        <Avatar name={profile.full_name || profile.email} size="xl" src={profile.picture_url} />
        <div>
          <p className="small muted" style={{ marginTop: 0 }}>
            Shown at the top right of the app. JPEG, PNG or WebP, up to 5 MB.
            {!profile.picture_url && " Until you add one, your initials are shown."}
          </p>
          {profile.editable && (
            <div className="row tight">
              <input ref={input} type="file" hidden aria-label="Choose a picture"
                accept={PICTURE_TYPES.join(",")}
                onChange={(e) => { choose(e.target.files?.[0]); e.target.value = ""; }} />
              <button type="button" onClick={() => input.current?.click()}>
                {profile.picture_url ? "Change picture" : "Add a picture"}
              </button>
              {profile.picture_url && (
                <button type="button" className="ghost" disabled={remove.isPending}
                  onClick={() => remove.mutate()}>Remove picture</button>
              )}
            </div>
          )}
          {problem && <Banner kind="bad">{problem}</Banner>}
        </div>
      </div>
      {file && <PictureCrop file={file} busy={upload.isPending}
        onCancel={() => setFile(null)} onDone={(picture) => upload.mutate(picture)} />}
    </Card>
  );
}
