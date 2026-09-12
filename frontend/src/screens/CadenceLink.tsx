import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import { Banner, Card } from "../components/ui";
import { api } from "../lib/api";

interface Cadence {
  name: string; cadence: string; is_muted: boolean;
  choices: { value: string; label: string }[];
}

/**
 * FR-3.33a — where the footer link in a digest lands. **No sign-in**: most
 * stakeholders have no login, and the token in the link is the authentication.
 * It can do exactly one thing — change how often this person hears, or stop it.
 */
export function CadenceLink() {
  const { token } = useParams();
  const qc = useQueryClient();
  const path = `/api/cadence/${token}`;
  const row = useQuery<Cadence>({
    queryKey: ["cadence", token], queryFn: () => api.get<Cadence>(path), retry: false,
  });
  const save = useMutation({
    mutationFn: (body: { cadence?: string; stop?: boolean }) => api.post<Cadence>(path, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["cadence", token] }),
  });

  if (row.isLoading) return <main style={{ padding: "2rem" }}>Checking the link…</main>;
  if (row.isError) {
    return (
      <main style={{ padding: "2rem" }}>
        <Banner kind="bad">{(row.error as Error).message}</Banner>
      </main>
    );
  }
  const data = row.data!;

  return (
    <main style={{ padding: "2rem", maxWidth: "34rem" }}>
      <h2>Your updates</h2>
      <Card>
        <p>{data.name}, choose how often you hear about progress on your work.</p>
        {save.isSuccess && <Banner kind="ok">Saved.</Banner>}
        {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
        {data.is_muted ? (
          <>
            <p><strong>You are not receiving updates.</strong></p>
            <button className="primary" onClick={() => save.mutate({ cadence: "weekly" })}>
              Start again, weekly
            </button>
          </>
        ) : (
          <>
            {data.choices.map((choice) => (
              <p key={choice.value}>
                <label style={{ display: "inline-flex", gap: ".45rem", alignItems: "center" }}>
                  <input type="radio" name="cadence" style={{ width: "auto" }}
                    checked={data.cadence === choice.value}
                    onChange={() => save.mutate({ cadence: choice.value })} />
                  {choice.label}
                </label>
              </p>
            ))}
            <button className="ghost" onClick={() => save.mutate({ stop: true })}>
              Stop sending me updates
            </button>
          </>
        )}
        <p className="small muted">
          This link changes only your own updates. You can use it again later.
        </p>
      </Card>
    </main>
  );
}
