/** People and permissions (owner, 2026-11-24): one screen per client company,
 *  reachable whenever intake forms or owner agreements are on for it, for the
 *  practice owner and the Client owner. It shows only the columns for what is
 *  on: owner agreements and signed PDFs with agreements, owner intake with
 *  intake forms. */
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { Banner, Card } from "../components/ui";
import type { Me } from "../lib/api";
import { agreements, type AccessRow } from "../lib/agreements";

type Flag = "agreements" | "signed_pdfs" | "intake" | "tax_numbers";
const COLUMNS: { flag: Flag; label: string; hint: string }[] = [
  { flag: "agreements", label: "Owner agreements", hint: "create, send, see" },
  { flag: "signed_pdfs", label: "Receives signed PDFs", hint: "and the signed text" },
  { flag: "intake", label: "Owner intake", hint: "review, send to Track, notices" },
  // Owner, 2026-11-24: nobody to start, the practice owner included.
  { flag: "tax_numbers", label: "See full tax numbers", hint: "with a code to their email" },
];

export function PeoplePermissions({ me: _me }: { me: Me }) {
  const { companyId = "" } = useParams();
  const qc = useQueryClient();
  const { data, error } = useQuery({ queryKey: ["agreement-access", companyId],
                                     queryFn: () => agreements.access(companyId) });
  const [rows, setRows] = useState<AccessRow[] | null>(null);
  const [said, setSaid] = useState("");
  const [problem, setProblem] = useState("");
  useEffect(() => { if (data) setRows(data.rows); }, [data]);
  if (error) return <div className="page"><Banner kind="warn">This page isn't here.</Banner>
    </div>;
  if (!data || !rows) return <div className="page"><p className="muted">Loading…</p></div>;
  const shown = COLUMNS.filter((c) => data.columns[c.flag]);
  const tick = (i: number, flag: Flag, on: boolean) =>
    setRows(rows.map((r, j) => (j === i ? { ...r, [flag]: on } : r)));
  return (
    <div className="page agreements">
      <div className="spread"><h1 style={{ margin: ".25rem 0" }}>People and permissions</h1>
        <span className="small" aria-live="polite">{said}</span></div>
      {problem && <Banner kind="warn">{problem}</Banner>}
      <Card title={data.company.name}>
        <p className="muted small" style={{ marginTop: 0 }}>Everyone active at
          {" "}{data.company.name} in ENHQ. A new person starts with nothing ticked. The practice
          owner always has {shown.some((c) => c.flag === "agreements") ? "agreements and " : ""}
          intake. Only the practice owner and the Client owner change this.</p>
        <div className="table-scroll">
          <table className="table access-table">
            <thead><tr><th>Person</th>{shown.map((c) => (
              <th key={c.flag}>{c.label}<span className="small muted"><br />{c.hint}</span></th>
            ))}</tr></thead>
            <tbody>
              {rows.map((r, i) => (
                <tr key={r.user_id}>
                  <td><strong>{r.name}</strong><br /><span className="small muted">{r.role}
                    </span></td>
                  {shown.map((c) => (
                    <td key={c.flag}><input type="checkbox" aria-label={`${r.name}: ${c.label}`}
                      checked={!!r[c.flag]}
                      disabled={r.practice_owner && c.flag !== "signed_pdfs"
                        && c.flag !== "tax_numbers"}
                      onChange={(e) => tick(i, c.flag, e.target.checked)} /></td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <button type="button" className="primary" onClick={async () => {
          setProblem("");
          try {
            const out = await agreements.saveAccess(companyId, rows);
            setRows(out.rows);
            qc.setQueryData(["agreement-access", companyId], out);
            setSaid("Permissions saved.");
          } catch (e) {
            setProblem((e as Error).message);
          }
        }}>Save permissions</button>
      </Card>
    </div>
  );
}
