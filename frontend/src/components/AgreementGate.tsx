import { useMutation, useQuery } from "@tanstack/react-query";

import { api } from "../lib/api";
import { Banner } from "./ui";

interface Terms { version: string; text: string; sha256: string; required: boolean }

/**
 * The beta agreement (P2): a practice owner reads and accepts it before
 * anything else. The server refuses every other call until they do; this is
 * the page in front of that. What is accepted is the exact text shown here,
 * identified by its hash.
 */
export function AgreementGate() {
  const terms = useQuery<Terms>({
    queryKey: ["agreement"], queryFn: () => api.get<Terms>("/api/agreement"),
  });
  const accept = useMutation({
    mutationFn: (t: Terms) => api.post("/api/agreement", { version: t.version, sha256: t.sha256 }),
    // A full load: every screen behind the gate starts fresh.
    onSuccess: () => window.location.assign("/"),
  });

  if (terms.isError) return <Banner kind="bad">{(terms.error as Error).message}</Banner>;
  if (!terms.data) return <main style={{ padding: "2rem" }}>Loading…</main>;
  const t = terms.data;
  const [title, ...rest] = t.text.split("\n");

  return (
    <main style={{ padding: "2.5rem 1rem", maxWidth: "44rem", margin: "0 auto" }}>
      <h1>{title.replace(/^#\s*/, "")}</h1>
      <article aria-label="Beta agreement">
        {rest.join("\n").split(/\n\s*\n/).filter((p) => p.trim()).map((p, i) => (
          <p key={i}>{p.trim()}</p>
        ))}
      </article>
      {accept.isError && <Banner kind="bad">{(accept.error as Error).message}</Banner>}
      <button className="primary" disabled={accept.isPending}
        onClick={() => accept.mutate(t)}>
        {accept.isPending ? "Recording…" : "I accept"}
      </button>
      <p className="small muted">Version {t.version}. Your acceptance is recorded with the
        date and the exact text above.</p>
    </main>
  );
}
