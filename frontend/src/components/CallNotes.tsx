import { useQuery } from "@tanstack/react-query";
import { ExternalLink, Users } from "lucide-react";

import { Card, Empty } from "./ui";
import { Me, MeetingNote, api } from "../lib/api";

/**
 * Call notes on a contact or a company (FR-5.8d).
 *
 * **The meeting is the point, not only the tasks it produced.** Opening
 * somebody's record six months later should show the calls they were in, not
 * merely whatever survived them — and a link back to the document, so the
 * record is checkable rather than merely assertable.
 *
 * Client users never see this: like the rest of Module 5 it carries the
 * practice's own notes about a client (matrix 11.1). The caller decides by not
 * rendering it, and the endpoint refuses them anyway.
 */
export function CallNotes({ me, contact, company }: {
  me: Me; contact?: string; company?: string;
}) {
  const key = contact ? ["meetings", "contact", contact] : ["meetings", "company", company];
  const query = contact ? `contact=${contact}` : `company=${company}`;
  const staff = me.role === "FF" || me.role === "CF" || me.role === "VA";

  const meetings = useQuery<MeetingNote[]>({
    queryKey: key,
    queryFn: () => api.get<MeetingNote[]>(`/api/meetings/?${query}`),
    enabled: staff && Boolean(contact || company),
  });

  if (!staff) return null;
  const rows = meetings.data ?? [];

  return (
    <Card title="Call notes">
      {rows.length === 0 ? (
        <Empty>
          No calls yet. Meetings appear here once a proposal from the notes
          folder has been approved.
        </Empty>
      ) : (
        <ul className="calls">
          {rows.map((row) => (
            <li key={row.id}>
              <p className="call-head">
                <strong>{row.title || "Meeting"}</strong>
                <span className="when">{row.date ?? "no date in the notes"}</span>
              </p>
              {/* The accepted summary or nothing: a discarded one means a
                  meeting with none, and inventing a fallback here would put
                  back what somebody chose to throw away. */}
              {row.summary
                ? <p style={{ whiteSpace: "pre-wrap" }}>{row.summary}</p>
                : <p className="small muted">No summary was kept for this call.</p>}
              <p className="tiny muted">
                {row.others.length > 0 && (
                  <><Users size={12} /> with {row.others.map((o) => o.name).join(", ")}</>
                )}
                {row.practice.length > 0 && (
                  <>{row.others.length > 0 ? " · " : ""}for the practice:{" "}
                    {row.practice.join(", ")}</>
                )}
              </p>
              {row.source_link && (
                <a className="small" href={row.source_link} target="_blank"
                  rel="noreferrer">
                  <ExternalLink size={12} /> {row.source_name || "Open the notes"}
                </a>
              )}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}
