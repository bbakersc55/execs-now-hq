import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { PageHead } from "../components/shell";
import { Banner, Card, Field } from "../components/ui";
import { Me, api } from "../lib/api";

export interface DigestSchedule {
  /** "Draft on": when each cycle's digests are written. ISO weekday, 1 is Monday. */
  draft_day: number; draft_day_name: string;
  /** 0 to 23, in the practice's time zone. */
  draft_hour: number;
  /** "Send on": when approved digests go out, and the approval cutoff. */
  day: number; day_name: string;
  hour: number;
  timezone: string;
  /** The cycle now open or coming, as instants. */
  next_draft_at?: string; next_send_at?: string;
  /** No part of the time to approve falls Monday to Friday, 9 to 5. */
  outside_working_hours?: boolean;
  /** Whether the practice owner has kept or changed it at least once. */
  confirmed: boolean;
}

type Times = Pick<DigestSchedule, "draft_day" | "draft_hour" | "day" | "hour">;

const hourOfWeek = (day: number, hour: number) => (day - 1) * 24 + hour;

/** Hours from Draft on to the Send on that follows it; 0 is the same moment. */
export function draftGapHours(t: Times) {
  return (((hourOfWeek(t.day, t.hour) - hourOfWeek(t.draft_day, t.draft_hour)) % 168) + 168) % 168;
}

/** True when no hour between Draft on and Send on is Monday to Friday, 9 to 5.
 *  The same rule the server applies (`digests.outside_working_hours`). */
export function outsideWorkingHours(t: Times) {
  const start = hourOfWeek(t.draft_day, t.draft_hour);
  for (let step = 0; step < draftGapHours(t); step += 1) {
    const slot = (start + step) % 168;
    const day = Math.floor(slot / 24);
    const hour = slot % 24;
    if (day < 5 && hour >= 9 && hour < 17) return false;
  }
  return true;
}

/** The one sentence that says what the two settings add up to. */
export function resultSentence(t: Times) {
  return `Work finished by ${DAYS[t.draft_day - 1]} ${hourLabel(t.draft_hour)} is included. `
    + `Approve any time until ${DAYS[t.day - 1]} ${hourLabel(t.hour)}, when approved digests `
    + "are sent.";
}

const DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

/** The zones most practices are in, by the name people use for them. */
const COMMON_ZONES: [string, string][] = [
  ["America/New_York", "Eastern"], ["America/Chicago", "Central"],
  ["America/Denver", "Mountain"], ["America/Phoenix", "Arizona (no daylight saving)"],
  ["America/Los_Angeles", "Pacific"], ["America/Anchorage", "Alaska"],
  ["Pacific/Honolulu", "Hawaii"],
];

function everyZone(): string[] {
  try {
    return (Intl as unknown as { supportedValuesOf(key: string): string[] })
      .supportedValuesOf("timeZone");
  } catch {
    return [];
  }
}

const HOURS = Array.from({ length: 24 }, (_, hour) => hour);

export function hourLabel(hour: number) {
  const twelve = hour % 12 === 0 ? 12 : hour % 12;
  return `${twelve}:00 ${hour < 12 ? "AM" : "PM"}`;
}

export function zoneLabel(zone: string) {
  const common = COMMON_ZONES.find(([id]) => id === zone);
  return common ? `${common[1]} (${zone})` : zone;
}

/** "Fridays at 8:00 AM Mountain (America/Denver)". */
export function scheduleSentence(s: DigestSchedule) {
  return `${s.day_name || DAYS[s.day - 1]}s at ${hourLabel(s.hour)} ${zoneLabel(s.timezone)}`;
}

export function useDigestSchedule(enabled = true) {
  return useQuery<DigestSchedule>({
    queryKey: ["digest-schedule"], enabled,
    queryFn: () => api.get<DigestSchedule>("/api/digests/schedule/"),
  });
}

/** Settings, Digests section (beta feedback, 2026-10-05, item E). */
export function DigestSettings() {
  const qc = useQueryClient();
  const schedule = useDigestSchedule();
  const [form, setForm] = useState<(Times & { timezone: string }) | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (schedule.data) {
      setForm({ draft_day: schedule.data.draft_day, draft_hour: schedule.data.draft_hour,
                day: schedule.data.day, hour: schedule.data.hour,
                timezone: schedule.data.timezone });
    }
  }, [schedule.data]);

  const save = useMutation({
    mutationFn: () => api.patch<DigestSchedule>("/api/digests/schedule/", form),
    onSuccess: (next) => { qc.setQueryData(["digest-schedule"], next); setSaved(true); },
  });

  if (schedule.isLoading || !form) return <p className="muted">Loading…</p>;
  if (schedule.isError || !schedule.data) {
    return <Banner kind="bad">The digest schedule could not be loaded.</Banner>;
  }
  const now = schedule.data;
  const changed = form.day !== now.day || form.hour !== now.hour
    || form.draft_day !== now.draft_day || form.draft_hour !== now.draft_hour
    || form.timezone !== now.timezone;
  const gap = draftGapHours(form);
  const tooClose = gap < 2;
  const others = everyZone().filter((z) => !COMMON_ZONES.some(([id]) => id === z));
  const listed = COMMON_ZONES.some(([id]) => id === form.timezone)
    || others.includes(form.timezone);
  const set = (change: Partial<typeof form>) => { setForm({ ...form, ...change }); setSaved(false); };

  return (
    <>
      <PageHead title="Digests"
        sub="When the progress digests your clients' stakeholders receive are written and sent." />
      <Card title="Digest day and time">
        <div className="row">
          <Field label="Draft on">
            <div className="inline">
              <select aria-label="Draft day" value={form.draft_day}
                onChange={(e) => set({ draft_day: Number(e.target.value) })}>
                {DAYS.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}
              </select>
              <select aria-label="Draft time" value={form.draft_hour}
                onChange={(e) => set({ draft_hour: Number(e.target.value) })}>
                {HOURS.map((hour) => <option key={hour} value={hour}>{hourLabel(hour)}</option>)}
              </select>
            </div>
          </Field>
          <Field label="Send on">
            <div className="inline">
              <select aria-label="Send day" value={form.day}
                onChange={(e) => set({ day: Number(e.target.value) })}>
                {DAYS.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}
              </select>
              <select aria-label="Send time" value={form.hour}
                onChange={(e) => set({ hour: Number(e.target.value) })}>
                {HOURS.map((hour) => <option key={hour} value={hour}>{hourLabel(hour)}</option>)}
              </select>
            </div>
          </Field>
          <Field label="Time zone">
            <select aria-label="Practice time zone" value={form.timezone}
              onChange={(e) => set({ timezone: e.target.value })}>
              {!listed && <option value={form.timezone}>{form.timezone}</option>}
              <optgroup label="Common">
                {COMMON_ZONES.map(([id, name]) => (
                  <option key={id} value={id}>{name} ({id})</option>
                ))}
              </optgroup>
              {others.length > 0 && (
                <optgroup label="All time zones">
                  {others.map((id) => <option key={id} value={id}>{id}</option>)}
                </optgroup>
              )}
            </select>
          </Field>
        </div>

        {/* The two settings, said as what will happen. It follows the
            controls, so it is read before Save is pressed. */}
        {tooClose ? (
          <Banner kind="bad">
            Draft on must be at least 2 hours before Send on, so there is time to approve.
          </Banner>
        ) : (
          <p aria-label="What this schedule does"><strong>{resultSentence(form)}</strong></p>
        )}
        {!tooClose && outsideWorkingHours(form) && (
          <Banner kind="warn">
            All of the time to approve these falls outside working hours (Monday to Friday,
            9 to 5). Digests nobody approves are not sent.
          </Banner>
        )}
        {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
        {saved && <Banner kind="ok">Saved.</Banner>}
        <button className="primary" disabled={!changed || tooClose || save.isPending}
          onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save"}
        </button>

        <ul className="small muted" style={{ marginBottom: 0 }}>
          <li><strong>Weekly</strong> digests are written at Draft on and sent at Send on.
            Each holds the work finished up to the moment it was written.</li>
          <li><strong>Monthly</strong> digests go on the first {DAYS[form.day - 1]} of the
            month, written on the {DAYS[form.draft_day - 1]} before it, and cover the month
            before.</li>
          <li>A stakeholder set to <strong>every update</strong> is not on this schedule:
            that digest is written half an hour after the work settles, has a day to be
            approved, and is sent as soon as it is.</li>
          <li>A change applies to digests written from now on. One already waiting on
            the <Link to="/digests">Digests</Link> screen keeps the time it was written
            with.</li>
          <li>The time zone is the practice's: it also sets the local hour of the app's
            other daily jobs.</li>
          <li>Nothing here sends a digest. Every digest still waits for the practice owner
            or an associate to approve it.</li>
          <li><strong>Reminders by email</strong> go to the practice owner, and to each
            associate for their own clients: when digests are ready to approve, a last
            call if any are still waiting, and a notice if any were not sent. They name
            who each digest is for and never include its text.</li>
        </ul>
      </Card>
    </>
  );
}

/**
 * Asked once, the first time the practice owner opens Digests: is the day and
 * time right? "Keep it" and "Change it" both answer it for good; afterward it
 * lives in Settings.
 */
export function DigestSchedulePrompt({ me }: { me: Me }) {
  const qc = useQueryClient();
  const owner = me.role === "FF";
  const schedule = useDigestSchedule(owner);
  const keep = useMutation({
    mutationFn: () => api.post<DigestSchedule>("/api/digests/schedule/confirm/"),
    onSuccess: (next) => qc.setQueryData(["digest-schedule"], next),
  });
  if (!owner || !schedule.data || schedule.data.confirmed) return null;

  const t = schedule.data;
  return (
    <Card title="When should your digests go out?">
      <p style={{ marginTop: 0 }}>
        They are written on <strong>{DAYS[t.draft_day - 1]}s at {hourLabel(t.draft_hour)}</strong>{" "}
        and sent on <strong>{DAYS[t.day - 1]}s at {hourLabel(t.hour)}</strong>{" "}
        ({zoneLabel(t.timezone)}). {resultSentence(t)}
      </p>
      {t.outside_working_hours && (
        <Banner kind="warn">
          All of the time to approve these falls outside working hours (Monday to Friday,
          9 to 5). Digests nobody approves are not sent.
        </Banner>
      )}
      <div className="row tight">
        <button className="primary" disabled={keep.isPending} onClick={() => keep.mutate()}>
          Keep this schedule
        </button>
        <Link className="button" to="/settings/digests">Change the days or times</Link>
      </div>
      <p className="small muted" style={{ marginBottom: 0 }}>
        You can change this later in Settings → Digests.
      </p>
    </Card>
  );
}

