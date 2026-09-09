import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Pill, when } from "../components/ui";
import { api, Contact, ImportBatch, ImportRow } from "../lib/api";

type Step = "upload" | "map" | "review" | "done";

const TARGETS = [
  "", "first_name", "last_name", "email", "company", "title", "notes",
  "background", "source",
];

interface DryRun { batch: ImportBatch; rows: ImportRow[]; errors: ImportRow[]; }
interface Ambiguous { row: ImportRow; candidates: Contact[]; }

export function ImportWizard() {
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [result, setResult] = useState<DryRun | null>(null);
  const [message, setMessage] = useState("");

  const batches = useQuery<ImportBatch[]>({
    queryKey: ["imports"], queryFn: () => api.get<ImportBatch[]>("/api/imports/"),
  });
  const ambiguous = useQuery<Ambiguous[]>({
    queryKey: ["ambiguous", result?.batch.id],
    queryFn: () => api.get<Ambiguous[]>(`/api/imports/${result!.batch.id}/ambiguous/`),
    enabled: !!result && (result.batch.counts.ambiguous ?? 0) > 0,
  });

  async function readHeaders(f: File) {
    const text = await f.text();
    const first = text.split(/\r?\n/)[0] ?? "";
    const cols = first.split(",").map((h) => h.trim().replace(/^"|"$/g, ""));
    setHeaders(cols);
    const guess: Record<string, string> = {};
    cols.forEach((col) => {
      const norm = col.toLowerCase().replace(/[^a-z]/g, "");
      if (norm.includes("first")) guess[col] = "first_name";
      else if (norm.includes("last")) guess[col] = "last_name";
      else if (norm.includes("email")) guess[col] = "email";
      else if (norm.includes("company") || norm.includes("org")) guess[col] = "company";
      else if (norm.includes("title") || norm.includes("role")) guess[col] = "title";
      else if (norm.includes("note")) guess[col] = "notes";
      else guess[col] = "";
    });
    setMapping(guess);
    setStep("map");
  }

  const dryRun = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.append("file", file!);
      form.append("mapping", JSON.stringify(mapping));
      return api.post<DryRun>("/api/imports/dry-run/", form);
    },
    onSuccess: (data) => { setResult(data); setStep("review"); },
  });

  const commit = useMutation({
    mutationFn: () => api.post(`/api/imports/${result!.batch.id}/commit/`, { mapping }),
    onSuccess: () => {
      setStep("done");
      setMessage("Import committed. Contacts, companies, and any notes column are now live.");
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["imports"] });
    },
  });

  const rollback = useMutation({
    mutationFn: (id: string) => api.post<{ report: Record<string, unknown> }>(
      `/api/imports/${id}/rollback/`
    ),
    onSuccess: (data) => {
      const r = data.report as { deleted: number; reverted: number; skipped: unknown[] };
      setMessage(
        `Rolled back: ${r.deleted} contacts deleted, ${r.reverted} reverted to their ` +
        `pre-import values, ${r.skipped.length} skipped because they were edited after the import.`
      );
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["imports"] });
    },
  });

  const counts = result?.batch.counts ?? {};

  return (
    <>
      <h2>CSV import</h2>
      <p className="sub">
        Upload, map columns, read the dry run, then commit. Nothing is written until you
        commit, and any commit can be rolled back.
      </p>

      <div className="stepper">
        {(["upload", "map", "review", "done"] as Step[]).map((s, i) => (
          <span key={s} className={`step ${step === s ? "on" : ""} ${
            (["upload", "map", "review", "done"] as Step[]).indexOf(step) > i ? "done" : ""}`}>
            {i + 1}. {{ upload: "Upload", map: "Map columns", review: "Dry run", done: "Committed" }[s]}
          </span>
        ))}
      </div>

      {message && <Banner kind="ok">{message}</Banner>}

      {step === "upload" && (
        <Card title="1. Choose a CSV">
          <input
            type="file" accept=".csv,text/csv"
            onChange={(e) => {
              const f = e.target.files?.[0] ?? null;
              setFile(f);
              if (f) readHeaders(f);
            }}
          />
          <p className="muted small" style={{ marginBottom: 0 }}>
            The first row must be a header row.
          </p>
        </Card>
      )}

      {step === "map" && (
        <Card
          title="2. Map your columns"
          actions={<button className="primary" disabled={dryRun.isPending}
            onClick={() => dryRun.mutate()}>
            {dryRun.isPending ? "Running…" : "Run dry run"}
          </button>}
        >
          <p className="muted small">
            A column mapped to <strong>notes</strong> becomes a real note attached to the
            contact — not a field on the record.
          </p>
          <table>
            <thead><tr><th>Column in your file</th><th>Import as</th></tr></thead>
            <tbody>
              {headers.map((h) => (
                <tr key={h}>
                  <td className="mono">{h}</td>
                  <td>
                    <select value={mapping[h] ?? ""}
                      onChange={(e) => setMapping({ ...mapping, [h]: e.target.value })}>
                      {TARGETS.map((t) => (
                        <option key={t} value={t}>{t === "" ? "— ignore —" : t}</option>
                      ))}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {step === "review" && result && (
        <>
          <Card title="3. Dry run — nothing has been written yet">
            <div className="row" style={{ marginBottom: "1rem" }}>
              <div><Pill kind="ok">{counts.create ?? 0} create</Pill></div>
              <div><Pill>{counts.update ?? 0} update</Pill></div>
              <div><Pill>{counts.skip ?? 0} skip</Pill></div>
              <div><Pill kind="warn">{counts.ambiguous ?? 0} need a decision</Pill></div>
              <div><Pill kind="bad">{counts.error ?? 0} error</Pill></div>
              <div style={{ flex: "0 0 auto" }}>
                <button className="primary" disabled={commit.isPending}
                  onClick={() => commit.mutate()}>
                  {commit.isPending ? "Committing…" : "Commit import"}
                </button>{" "}
                <button onClick={() => { setStep("upload"); setResult(null); }}>Start over</button>
              </div>
            </div>
          </Card>

          {(ambiguous.data ?? []).length > 0 && (
            <Card title={`Duplicates to resolve (${ambiguous.data!.length})`}>
              <p className="muted small">
                More than one existing contact matched these rows. The import will not
                guess — resolve each one by merging the duplicates, then re-run the dry
                run so the row matches a single contact.
              </p>
              {ambiguous.data!.map((a) => (
                <div key={a.row.id} className="card" style={{ marginBottom: ".7rem" }}>
                  <div className="spread">
                    <strong className="small">
                      Row {a.row.row_number}:{" "}
                      <span className="mono">
                        {Object.entries(a.row.raw).filter(([, v]) => v)
                          .map(([k, v]) => `${k}=${v}`).join("  ")}
                      </span>
                    </strong>
                    <Pill kind="warn">needs a decision</Pill>
                  </div>
                  <table style={{ marginTop: ".5rem" }}>
                    <thead><tr><th>Existing contact</th><th>Email</th><th></th></tr></thead>
                    <tbody>
                      {a.candidates.map((cand, i) => (
                        <tr key={cand.id}>
                          <td>
                            <Link to={`/contacts/${cand.id}`}>
                              {cand.first_name} {cand.last_name}
                            </Link>
                            {cand.title && <span className="muted"> · {cand.title}</span>}
                          </td>
                          <td className="mono small">{cand.emails[0]?.address ?? "—"}</td>
                          <td className="right">
                            {i === 0 && a.candidates.length > 1 && (
                              <Link
                                className="btn"
                                to={`/merge/${a.candidates[0].id}/${a.candidates[1].id}`}
                              >
                                Merge these two…
                              </Link>
                            )}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </Card>
          )}

          {result.errors.length > 0 && (
            <Card title="Rows needing attention">
              <table>
                <thead><tr><th>Row</th><th>Outcome</th><th>Why</th></tr></thead>
                <tbody>
                  {result.errors.map((r) => (
                    <tr key={r.id}>
                      <td className="mono">{r.row_number}</td>
                      <td><Pill kind={r.outcome === "error" ? "bad" : "warn"}>{r.outcome}</Pill></td>
                      <td className="small">{r.error_text}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Card>
          )}

          <Card title="First 20 rows as they will be written">
            <table>
              <thead><tr><th>Row</th><th>Outcome</th><th>Data</th></tr></thead>
              <tbody>
                {result.rows.map((r) => (
                  <tr key={r.id}>
                    <td className="mono">{r.row_number}</td>
                    <td><Pill>{r.outcome}</Pill></td>
                    <td className="small mono">
                      {Object.entries(r.raw).filter(([, v]) => v).map(([k, v]) => `${k}=${v}`).join("  ")}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </Card>
        </>
      )}

      <Card title="Import history">
        {(batches.data ?? []).length === 0 ? <Empty>No imports yet.</Empty> : (
          <table>
            <thead><tr><th>File</th><th>When</th><th>Status</th><th>Counts</th><th></th></tr></thead>
            <tbody>
              {batches.data!.map((b) => (
                <tr key={b.id}>
                  <td className="mono">{b.filename}</td>
                  <td className="muted small">{when(b.created_at)}</td>
                  <td><Pill kind={b.status === "committed" ? "ok" : b.status === "rolled_back" ? "bad" : ""}>
                    {b.status.replace(/_/g, " ")}</Pill></td>
                  <td className="small mono">
                    {Object.entries(b.counts).map(([k, v]) => `${k}:${v}`).join(" ")}
                  </td>
                  <td className="right">
                    {b.status === "committed" && (
                      <button className="danger" disabled={rollback.isPending}
                        onClick={() => rollback.mutate(b.id)}>
                        Roll back
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}
