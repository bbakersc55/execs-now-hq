import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { Banner, Card, Empty, Pill } from "../components/ui";
import { api } from "../lib/api";

interface Effective {
  is_local: boolean;
  from_env: string[];
  entries: { id: string; address: string; note: string; removable: boolean }[];
  effective: string[];
}

/**
 * FR-0.7 / H6 — who may receive REAL mail from this localhost build.
 *
 * Rendered only when the build is local; the API 404s otherwise, so there are
 * two independent locks on the same door rather than a hidden button.
 */
export function DevAllowlist() {
  const qc = useQueryClient();
  const [address, setAddress] = useState("");
  const [note, setNote] = useState("");
  const [error, setError] = useState("");

  const list = useQuery<Effective>({
    queryKey: ["dev-allowlist"],
    queryFn: () => api.get<Effective>("/api/dev-allowlist/effective/"),
  });

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["dev-allowlist"] });
    // The Outbox badges are computed from this list — refresh them too.
    qc.invalidateQueries({ queryKey: ["outbox"] });
  };

  const add = useMutation({
    mutationFn: () => api.post("/api/dev-allowlist/", { address, note }),
    onSuccess: () => { setAddress(""); setNote(""); setError(""); invalidate(); },
    onError: (e: Error & { data?: Record<string, unknown> }) => {
      const detail = e.data
        ? Object.values(e.data).flat().join(" ")
        : e.message;
      setError(detail || e.message);
    },
  });

  const remove = useMutation({
    mutationFn: (id: string) => api.del(`/api/dev-allowlist/${id}/`),
    onSuccess: invalidate,
  });

  const data = list.data;

  return (
    <Card title="Dev builds — who may receive real mail">
      <Banner kind="warn">
        This section exists only on a localhost build. Everything the app sends goes to
        Mailpit <strong>unless</strong> the recipient is an exact match below — in which
        case a real person gets a real email.
      </Banner>

      <p className="muted small">
        Exact addresses only. A bare domain or a wildcard is refused: one entry like
        <code> @getexecutivesnow.com</code> would put every colleague and client at that
        domain back in range (assumption H6). Every real send from a dev build is
        audited and badged in the Outbox.
      </p>

      {error && <Banner kind="bad">{error}</Banner>}

      <form className="row" onSubmit={(e) => { e.preventDefault(); add.mutate(); }}>
        <div style={{ flex: "2 1 240px" }}>
          <input value={address} placeholder="name@example.com" aria-label="Address to allow"
            onChange={(e) => setAddress(e.target.value)} />
        </div>
        <div style={{ flex: "1 1 160px" }}>
          <input value={note} placeholder="note (optional)" aria-label="Note"
            onChange={(e) => setNote(e.target.value)} />
        </div>
        <div style={{ flex: "0 0 auto" }}>
          <button className="primary" type="submit" disabled={!address.trim() || add.isPending}>
            Allow real delivery
          </button>
        </div>
      </form>

      {!data ? <Empty>Loading…</Empty> : (
        <table>
          <thead><tr><th>Address</th><th>Source</th><th>Note</th><th></th></tr></thead>
          <tbody>
            {data.from_env.map((a) => (
              <tr key={`env-${a}`}>
                <td className="mono">{a}</td>
                <td><Pill>.env</Pill></td>
                <td className="muted small">
                  Set in the environment — the floor this app cannot lower.
                </td>
                <td className="right muted small">locked</td>
              </tr>
            ))}
            {data.entries.map((e) => (
              <tr key={e.id}>
                <td className="mono">{e.address}</td>
                <td><Pill kind="ai">added here</Pill></td>
                <td className="muted small">{e.note || "—"}</td>
                <td className="right">
                  <button className="danger" disabled={remove.isPending}
                    aria-label={`Remove ${e.address}`}
                    onClick={() => remove.mutate(e.id)}>
                    Remove
                  </button>
                </td>
              </tr>
            ))}
            {data.effective.length === 0 && (
              <tr><td colSpan={4}>
                <Empty>
                  Nothing is allow-listed, so <strong>nothing can reach a real person</strong>{" "}
                  from this build. Everything goes to Mailpit.
                </Empty>
              </td></tr>
            )}
          </tbody>
        </table>
      )}
    </Card>
  );
}
