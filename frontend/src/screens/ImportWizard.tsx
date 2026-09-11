import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, Pill, when } from "../components/ui";
import {
  Contact, ImportBatch, ImportRow, MappingProfile, ValueBlock, ValueRule,
  ValueScan, api,
} from "../lib/api";

type Step = "upload" | "map" | "values" | "review" | "done";

const STEP_LABELS: Record<Step, string> = {
  upload: "Upload",
  map: "Map columns",
  values: "Map values",
  review: "Dry run",
  done: "Committed",
};

const TARGETS = [
  "", "first_name", "last_name", "email", "phone", "company", "title",
  "contact_type", "pipeline_stage", "tags", "notes", "background", "source",
];

/** The two columns that go through the value-mapping sub-step. */
const VALUE_TARGETS = ["contact_type", "pipeline_stage"] as const;
type ValueTarget = (typeof VALUE_TARGETS)[number];

/** Targets whose behaviour is not obvious from the name alone. */
const TARGET_HELP: Record<string, string> = {
  phone: "first phone column becomes the primary number",
  contact_type: "you map each value in the next step",
  pipeline_stage: "you pick a pipeline, then map each value",
  tags: "comma or semicolon separated",
  notes: "becomes a real note, not a field",
};

interface DryRun { batch: ImportBatch; rows: ImportRow[]; errors: ImportRow[]; }
interface Ambiguous { row: ImportRow; candidates: Contact[]; }

export function ImportWizard() {
  const qc = useQueryClient();
  const [step, setStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [headers, setHeaders] = useState<string[]>([]);
  const [mapping, setMapping] = useState<Record<string, string>>({});
  const [valueMapping, setValueMapping] = useState<Record<string, ValueBlock>>({});
  const [scan, setScan] = useState<ValueScan | null>(null);
  const [result, setResult] = useState<DryRun | null>(null);
  const [message, setMessage] = useState("");
  const [profileName, setProfileName] = useState("");

  const batches = useQuery<ImportBatch[]>({
    queryKey: ["imports"], queryFn: () => api.get<ImportBatch[]>("/api/imports/"),
  });
  const profiles = useQuery<MappingProfile[]>({
    queryKey: ["import-profiles"],
    queryFn: () => api.get<MappingProfile[]>("/api/import-profiles/"),
  });
  const ambiguous = useQuery<Ambiguous[]>({
    queryKey: ["ambiguous", result?.batch.id],
    queryFn: () => api.get<Ambiguous[]>(`/api/imports/${result!.batch.id}/ambiguous/`),
    enabled: !!result && (result.batch.counts.ambiguous ?? 0) > 0,
  });

  const valueColumns = VALUE_TARGETS.filter((t) =>
    Object.values(mapping).includes(t));
  const needsValueStep = valueColumns.length > 0;

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
      else if (norm.includes("phone") || norm.includes("mobile") || norm.includes("cell"))
        guess[col] = "phone";
      else if (norm.includes("company") || norm.includes("org")) guess[col] = "company";
      else if (norm.includes("title") || norm.includes("role")) guess[col] = "title";
      else if (norm.includes("tag")) guess[col] = "tags";
      // The owner's CRM has BOTH: a Status (type) column and a separate Stage
      // column. Guessing them apart is the whole point.
      else if (norm.includes("stage")) guess[col] = "pipeline_stage";
      else if (norm.includes("status") || norm.includes("type"))
        guess[col] = "contact_type";
      else if (norm.includes("note")) guess[col] = "notes";
      else guess[col] = "";
    });
    setMapping(guess);
    setStep("map");
  }

  const scanValues = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.append("file", file!);
      form.append("mapping", JSON.stringify(mapping));
      return api.post<ValueScan>("/api/imports/scan-values/", form);
    },
    onSuccess: (data) => {
      setScan(data);
      // Pre-select nothing: an unmapped value is a visible error, and a guess
      // here would put contacts into the wrong stage without being read.
      setStep("values");
    },
  });

  const dryRun = useMutation({
    mutationFn: async () => {
      const form = new FormData();
      form.append("file", file!);
      form.append("mapping", JSON.stringify(mapping));
      form.append("value_mapping", JSON.stringify(valueMapping));
      return api.post<DryRun>("/api/imports/dry-run/", form);
    },
    onSuccess: (data) => { setResult(data); setStep("review"); },
  });

  const commit = useMutation({
    mutationFn: () => api.post(`/api/imports/${result!.batch.id}/commit/`),
    onSuccess: () => {
      setStep("done");
      setMessage("Import committed. Contacts, companies, phones, tags, types and any notes column are now live.");
      qc.invalidateQueries({ queryKey: ["contacts"] });
      qc.invalidateQueries({ queryKey: ["imports"] });
    },
  });

  const saveProfile = useMutation({
    mutationFn: () => api.post<MappingProfile>("/api/import-profiles/", {
      name: profileName, mapping, value_mapping: valueMapping,
    }),
    onSuccess: (p) => {
      setMessage(`Saved mapping “${p.name}”. Both the columns and the value mapping are remembered.`);
      setProfileName("");
      qc.invalidateQueries({ queryKey: ["import-profiles"] });
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

  function applyProfile(p: MappingProfile) {
    setMapping(p.mapping ?? {});
    setValueMapping(p.value_mapping ?? {});
    setMessage(`Loaded mapping “${p.name}”.`);
  }

  function block(target: ValueTarget): ValueBlock {
    return valueMapping[target] ?? {
      column: Object.entries(mapping).find(([, t]) => t === target)?.[0] ?? "",
      values: {},
    };
  }

  function setBlock(target: ValueTarget, patch: Partial<ValueBlock>) {
    setValueMapping({ ...valueMapping, [target]: { ...block(target), ...patch } });
  }

  function setRule(target: ValueTarget, value: string, patch: ValueRule) {
    const current = block(target);
    setBlock(target, {
      values: { ...current.values, [value]: { ...(current.values[value] ?? {}), ...patch } },
    });
  }

  /** Stages of one pipeline id, for a stage dropdown. */
  function stagesOf(pipelineId: string | undefined) {
    return (scan?.pipelines ?? []).find((p) => p.id === pipelineId)?.stages ?? [];
  }

  const counts = result?.batch.counts ?? {};
  const order: Step[] = ["upload", "map", "values", "review", "done"];

  return (
    <>
      <h2>CSV import</h2>
      <p className="sub">
        Upload, map columns, map the values in your status column, read the dry run, then
        commit. Nothing is written until you commit, and any commit can be rolled back.
      </p>

      <div className="stepper">
        {order.map((s, i) => (
          <span key={s} className={`step ${step === s ? "on" : ""} ${
            order.indexOf(step) > i ? "done" : ""}`}>
            {i + 1}. {STEP_LABELS[s]}
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
          actions={
            <button className="primary" disabled={dryRun.isPending || scanValues.isPending}
              onClick={() => (needsValueStep ? scanValues.mutate() : dryRun.mutate())}>
              {needsValueStep ? "Next: map values" : "Run dry run"}
            </button>
          }
        >
          <p className="muted small">
            A column mapped to <strong>notes</strong> becomes a real note attached to the
            contact — not a field on the record. Map <strong>two</strong> columns to{" "}
            <strong>phone</strong> to import a second number; the first one becomes the
            contact's primary. If your file has both a <strong>Status</strong> and a
            separate <strong>Stage</strong> column, map them to{" "}
            <strong>contact_type</strong> and <strong>pipeline_stage</strong> — they are
            different facts and both are kept.
          </p>

          {(profiles.data ?? []).length > 0 && (
            <p className="small">
              Load a saved mapping:{" "}
              {profiles.data!.map((p) => (
                <button key={p.id} className="ghost" style={{ marginRight: ".3rem" }}
                  onClick={() => applyProfile(p)}>
                  {p.name}
                </button>
              ))}
            </p>
          )}

          <table>
            <thead><tr><th>Column in your file</th><th>Import as</th><th></th></tr></thead>
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
                  <td className="muted small">{TARGET_HELP[mapping[h] ?? ""] ?? ""}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      )}

      {step === "values" && scan && (
        <>
          {scan.targets.map((t) => {
            const target = t.target;
            const blk = block(target);
            const isStageColumn = target === "pipeline_stage";
            const columnPipeline = blk.pipeline;
            const unmapped = t.values.filter((v) => {
              const r = blk.values[v.value];
              return !r || (!r.ignore && !r.contact_type && !r.stage);
            });
            return (
              <Card key={target} title={`2b. Map the values in “${t.column}”`}>
                <p className="muted small">
                  Every distinct value in that column, with how many rows carry it.
                  Anything left unmapped becomes a row error in the dry run rather than
                  being silently dropped.
                </p>

                {isStageColumn && (
                  <div style={{ marginBottom: ".8rem" }}>
                    <label>Which pipeline is this column about?</label>{" "}
                    <select value={columnPipeline ?? ""}
                      onChange={(e) => setBlock(target, {
                        pipeline: e.target.value, values: {},
                      })}>
                      <option value="">Choose a pipeline…</option>
                      {scan.pipelines.map((p) => (
                        <option key={p.id} value={p.id}>{p.name}</option>
                      ))}
                    </select>
                    <p className="muted small" style={{ marginBottom: 0 }}>
                      The whole column belongs to one pipeline. A Status column that also
                      places people can name a different pipeline per value.
                    </p>
                  </div>
                )}

                {isStageColumn && !columnPipeline ? (
                  <Empty>Choose a pipeline to map this column's values.</Empty>
                ) : (
                  <>
                    {unmapped.length > 0 && (
                      <Banner kind="warn">
                        {unmapped.length} value{unmapped.length === 1 ? "" : "s"} still
                        unmapped:{" "}
                        <span className="mono">{unmapped.map((v) => v.value).join(", ")}</span>
                      </Banner>
                    )}
                    <table>
                      <thead>
                        <tr>
                          <th>Value</th><th>Rows</th>
                          {!isStageColumn && <th>Contact type</th>}
                          {!isStageColumn && <th>Pipeline</th>}
                          <th>Stage</th><th></th>
                        </tr>
                      </thead>
                      <tbody>
                        {t.values.map((v) => {
                          const rule = blk.values[v.value] ?? {};
                          const rulePipeline = isStageColumn ? columnPipeline : rule.pipeline;
                          const stages = stagesOf(rulePipeline);
                          const chosen = stages.find((st) => st.code === rule.stage);
                          const isSale = chosen?.semantic === "won"
                            && scan.pipelines.find((p) => p.id === rulePipeline)?.kind === "sales";
                          return (
                            <tr key={v.value}>
                              <td className="mono">{v.value}</td>
                              <td className="muted small">{v.count}</td>
                              {!isStageColumn && (
                                <td>
                                  <select value={rule.contact_type ?? ""} disabled={rule.ignore}
                                    onChange={(e) => setRule(target, v.value, {
                                      contact_type: e.target.value,
                                    })}>
                                    <option value="">— none —</option>
                                    {scan.contact_types.map((ct) => (
                                      <option key={ct.code} value={ct.code}>{ct.label}</option>
                                    ))}
                                  </select>
                                </td>
                              )}
                              {!isStageColumn && (
                                <td>
                                  <select value={rule.pipeline ?? ""} disabled={rule.ignore}
                                    onChange={(e) => setRule(target, v.value, {
                                      pipeline: e.target.value, stage: "",
                                    })}>
                                    <option value="">— no pipeline —</option>
                                    {scan.pipelines.map((p) => (
                                      <option key={p.id} value={p.id}>{p.name}</option>
                                    ))}
                                  </select>
                                </td>
                              )}
                              <td>
                                <select value={rule.stage ?? ""}
                                  disabled={rule.ignore || !rulePipeline}
                                  onChange={(e) => setRule(target, v.value, {
                                    stage: e.target.value,
                                  })}>
                                  <option value="">— leave alone —</option>
                                  {stages.slice().sort((a, b) => a.position - b.position)
                                    .map((st) => (
                                      <option key={st.id} value={st.code}>{st.label}</option>
                                    ))}
                                </select>
                                {isSale && (
                                  <div className="muted small">
                                    also adds the client type and flags the company
                                  </div>
                                )}
                              </td>
                              <td>
                                <label className="small">
                                  <input type="checkbox" checked={!!rule.ignore}
                                    onChange={(e) => setRule(target, v.value, {
                                      ignore: e.target.checked, contact_type: "",
                                      pipeline: "", stage: "",
                                    })} />{" "}
                                  ignore
                                </label>
                              </td>
                            </tr>
                          );
                        })}
                      </tbody>
                    </table>
                  </>
                )}
              </Card>
            );
          })}

          <Card title="Remember this mapping">
            <p className="muted small">
              Saves the column mapping <em>and</em> every value mapping together, so the
              next export from the same system maps in one click.
            </p>
            <input placeholder="e.g. Outlook export" value={profileName}
              onChange={(e) => setProfileName(e.target.value)} />{" "}
            <button disabled={!profileName || saveProfile.isPending}
              onClick={() => saveProfile.mutate()}>
              Save mapping
            </button>
            <p style={{ marginTop: ".8rem", marginBottom: 0 }}>
              <button className="ghost" onClick={() => setStep("map")}>← Back to columns</button>{" "}
              <button className="primary" disabled={dryRun.isPending}
                onClick={() => dryRun.mutate()}>
                {dryRun.isPending ? "Running…" : "Run dry run"}
              </button>
            </p>
          </Card>
        </>
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
            {result.rows.some((r) => r.preview?.fires_client_invariant) && (
              <Banner kind="warn">
                Some rows are mapped to stage <strong>Client</strong>. Committing adds the
                client contact type and flags their company as a client company — the same
                as moving them by hand. It does <strong>not</strong> fire your stage
                automations: an import is history, not a move happening today.
              </Banner>
            )}
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
              <thead>
                <tr>
                  <th>Row</th><th>Outcome</th><th>Name</th><th>Phones</th>
                  <th>Type</th><th>Pipelines</th><th>Tags</th>
                </tr>
              </thead>
              <tbody>
                {result.rows.map((r) => {
                  const p = r.preview;
                  return (
                    <tr key={r.id}>
                      <td className="mono">{r.row_number}</td>
                      <td><Pill>{r.outcome}</Pill></td>
                      <td className="small">
                        {p ? `${p.first_name} ${p.last_name}`.trim() : "—"}
                        {p?.company && <span className="muted"> · {p.company}</span>}
                      </td>
                      <td className="small mono">
                        {p && p.phones.length > 0
                          ? p.phones.map((ph) => (
                              <div key={ph.number}>
                                {ph.number}{ph.is_primary && <span className="muted"> primary</span>}
                              </div>
                            ))
                          : "—"}
                      </td>
                      <td className="small">
                        {p?.contact_type_label
                          ? <Pill>{p.contact_type_label}</Pill>
                          : p?.value_ignored ? <span className="muted">ignored</span> : "—"}
                      </td>
                      <td className="small">
                        {p && p.placements.length > 0
                          ? p.placements.map((pl) => (
                              <div key={pl.pipeline}>
                                <Pill kind={pl.fires_client_invariant ? "warn" : ""}>
                                  {pl.stage}
                                </Pill>{" "}
                                <span className="muted">{pl.pipeline}</span>
                              </div>
                            ))
                          : "—"}
                      </td>
                      <td className="small">
                        {p && p.tags.length > 0
                          ? p.tags.map((t) => <Pill key={t}>{t}</Pill>)
                          : "—"}
                      </td>
                    </tr>
                  );
                })}
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
