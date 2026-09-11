import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";

import { Banner, Card } from "../components/ui";
import { NoteFull, api } from "../lib/api";

/**
 * FR-2.12 — where the reset email lands. Opening this page changes nothing
 * (a mail scanner following the link is harmless); only the button clears.
 */
export function PinReset() {
  const { token } = useParams();
  const navigate = useNavigate();
  const target = useQuery<{ note: string; title: string }>({
    queryKey: ["pin-reset", token],
    queryFn: () => api.get(`/api/notes/pin-reset/confirm/?token=${encodeURIComponent(token ?? "")}`),
    retry: false,
  });
  const clear = useMutation({
    mutationFn: () => api.post<NoteFull>("/api/notes/pin-reset/confirm/", { token }),
    onSuccess: (n) => navigate(`/notes/${n.id}`),
  });

  if (target.isLoading) return <p>Checking the link…</p>;
  if (target.isError) return <Banner kind="bad">{(target.error as Error).message}</Banner>;

  return (
    <Card title="Clear a note's PIN">
      <p>
        This clears the PIN on <strong>“{target.data!.title}”</strong>. It does not tell you what
        the PIN was.
      </p>
      <p>
        Once cleared, the note is readable by everyone who can normally see it, until someone
        sets a new PIN. The reset is recorded in the audit log.
      </p>
      {clear.isError && <Banner kind="bad">{(clear.error as Error).message}</Banner>}
      <div className="row">
        <button className="danger" onClick={() => clear.mutate()} disabled={clear.isPending}>Clear the PIN</button>
        <Link to="/notes">Leave it locked</Link>
      </div>
    </Card>
  );
}
