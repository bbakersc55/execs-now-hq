import { useMutation } from "@tanstack/react-query";
import { useEffect, useRef } from "react";
import { useParams } from "react-router-dom";

import { Banner, Card } from "../components/ui";
import { api } from "../lib/api";

interface Preferences {
  practice: string;
  /** The category the link was for. */
  category: "marketing" | "updates";
  categories: { category: "marketing" | "updates"; label: string; unsubscribed: boolean }[];
}

/**
 * Where an unsubscribe link lands (owner, 2026-09-28). **No sign-in** — the
 * signed link is the authority. Landing here unsubscribes from the category
 * the email was in, and only that one; the page says what they left and
 * offers the other, and an undo. Opening the link without this page running
 * (a mail scanner) changes nothing: the server only acts on the page's POST.
 */
export function Unsubscribe() {
  const { token } = useParams();
  const path = `/api/unsubscribe/${token}`;
  const change = useMutation({
    mutationFn: (body: { category?: string; action?: "resubscribe" }) =>
      api.post<Preferences>(path, body),
  });
  const once = useRef(false);
  useEffect(() => {
    if (once.current) return;
    once.current = true;
    change.mutate({});
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  if (change.isError) {
    return (
      <main className="public-page">
        <Banner kind="bad">{(change.error as Error).message}</Banner>
      </main>
    );
  }
  const data = change.data;
  if (!data) return <main className="public-page">Updating your preferences…</main>;
  const left = data.categories.find((c) => c.category === data.category)!;
  const other = data.categories.find((c) => c.category !== data.category)!;

  return (
    <main className="public-page">
      <h2>{data.practice ? `Email from ${data.practice}` : "Your email preferences"}</h2>
      <Card>
        {left.unsubscribed ? (
          <>
            <p><strong>You are unsubscribed from {left.label}.</strong> You will not get
              them again.</p>
            <p className="small muted">
              Emails you need to act on — sign-in links, or documents you asked for — are
              not affected.
            </p>
            <button className="small" disabled={change.isPending}
              onClick={() => change.mutate({ category: left.category, action: "resubscribe" })}>
              Undo — keep sending me {left.label}
            </button>
          </>
        ) : (
          <>
            <p>You are receiving {left.label} again.</p>
            <button className="small" disabled={change.isPending}
              onClick={() => change.mutate({ category: left.category })}>
              Unsubscribe from {left.label}
            </button>
          </>
        )}
      </Card>
      <Card>
        {other.unsubscribed ? (
          <>
            <p>You are also unsubscribed from {other.label}.</p>
            <button className="small" disabled={change.isPending}
              onClick={() => change.mutate({ category: other.category, action: "resubscribe" })}>
              Keep sending me {other.label}
            </button>
          </>
        ) : (
          <>
            <p>You still receive {other.label}.</p>
            <button className="small" disabled={change.isPending}
              onClick={() => change.mutate({ category: other.category })}>
              Unsubscribe from {other.label} too
            </button>
          </>
        )}
      </Card>
    </main>
  );
}
