import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import { Card, Empty, Field, when } from "../components/ui";
import { Me, ProgressReport, api } from "../lib/api";

/**
 * FR-3.38 — the on-demand progress report: the same content as a digest, pulled
 * instead of sent. No email, no approval, and it consumes nothing, so reading it
 * never eats the Friday email.
 */
export function Report(_props: { me: Me }) {
  const [days, setDays] = useState(30);
  const report = useQuery<ProgressReport>({
    queryKey: ["progress-report", days],
    queryFn: () => api.get<ProgressReport>(`/api/progress-report/?days=${days}`),
  });

  return (
    <>
      <h2>Progress report</h2>
      <p className="sub">
        Everything that moved on your work in the period, as it would read in an emailed
        update. Opening this sends nothing to anyone.
      </p>
      <Card actions={
        <Field label="Period">
          <select aria-label="Period" value={days} onChange={(e) => setDays(Number(e.target.value))}>
            <option value={7}>Last 7 days</option>
            <option value={30}>Last 30 days</option>
            <option value={90}>Last 90 days</option>
          </select>
        </Field>
      }>
        {report.isLoading ? <p>Loading…</p>
          : !report.data?.body_text
            ? <Empty>Nothing moved in this period.</Empty>
            : (
              <pre style={{ whiteSpace: "pre-wrap", fontFamily: "inherit", margin: 0 }}>
                {report.data.body_text}
              </pre>
            )}
        {report.data && (
          <p className="small muted">
            {when(report.data.since)} to {when(report.data.until)} ·{" "}
            {report.data.updates.length} update{report.data.updates.length === 1 ? "" : "s"}
          </p>
        )}
      </Card>
    </>
  );
}
