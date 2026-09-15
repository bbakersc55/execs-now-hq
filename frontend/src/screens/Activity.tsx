import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { Banner, Card, Empty, when } from "../components/ui";
import { ActivityEntry, Me, api } from "../lib/api";

const LINK: Record<string, string> = { task: "/tasks", project: "/work/projects", goal: "/work/goals" };

/**
 * FR-3.41 — the client portal's activity log: everything that has happened on
 * the company's work, newest first. Read-only for everyone; there is nothing
 * here to edit or remove. Internal comments and hidden work are never sent to
 * this screen at all.
 */
export function Activity({ me }: { me: Me }) {
  const log = useQuery<ActivityEntry[]>({
    queryKey: ["portal-activity"],
    queryFn: () => api.get<ActivityEntry[]>("/api/portal-activity/"),
    enabled: me.role === "FCC" || me.role === "ECC",
    refetchInterval: 60_000,
  });

  if (log.isError) return <Banner kind="bad">The activity log is not available to you.</Banner>;
  const rows = log.data ?? [];

  return (
    <>
      <h2>Activity</h2>
      <p className="sub">
        Everything that has happened on your company's work, newest first. Nobody can edit or
        remove an entry.
      </p>
      <Card>
        {rows.length === 0 ? <Empty>Nothing has happened yet.</Empty> : (
          <ul className="timeline">
            {rows.map((e) => (
              <li key={e.id}>
                <div>
                  <strong>{e.by}</strong>
                  {e.on_behalf_of && <> on behalf of <strong>{e.on_behalf_of}</strong></>}{" "}
                  {e.text}
                </div>
                <div className="when">
                  {when(e.at)}
                  {e.entity && LINK[e.entity.type] && (
                    <> · <Link to={`${LINK[e.entity.type]}/${e.entity.id}`}>open</Link></>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>
    </>
  );
}
