import { Link } from "react-router-dom";

import { CalendarMeeting } from "../lib/api";

function clock(value: string, zone?: string) {
  return new Date(value).toLocaleTimeString([], {
    hour: "numeric", minute: "2-digit", ...(zone ? { timeZone: zone } : {}) });
}

function day(value: string, zone?: string) {
  return new Date(value).toLocaleDateString([], {
    month: "short", day: "numeric", ...(zone ? { timeZone: zone } : {}) });
}

/** Meetings with the contacts and companies they matched, each a link to its
 *  record (2026-10-27). `withDay` for a list across several days. */
export function MeetingList({ events, zone, withDay = false }: {
  events: CalendarMeeting[]; zone?: string; withDay?: boolean;
}) {
  return (
    <ul className="meetings">
      {events.map((e) => (
        <li key={e.id} className={e.past ? "past" : ""}>
          <span className="when small">
            {withDay && <>{day(e.starts_at, zone)}<br /></>}
            {e.all_day ? "All day" : clock(e.starts_at, zone)}
          </span>
          <span className="what">
            {e.web_link
              ? <a href={e.web_link} target="_blank" rel="noreferrer">{e.title}</a>
              : <strong>{e.title}</strong>}
            {e.on_calendar_of && <span className="small muted"> · {e.on_calendar_of}</span>}
            {(e.contacts.length > 0 || e.companies.length > 0) && (
              <span className="links">
                {e.companies.map((c) => <Link key={c.id} to={`/companies/${c.id}`}>{c.name}</Link>)}
                {e.contacts.map((c) => <Link key={c.id} to={`/contacts/${c.id}`}>{c.name}</Link>)}
              </span>
            )}
          </span>
        </li>
      ))}
    </ul>
  );
}
