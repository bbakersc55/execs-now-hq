import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { PageHead } from "../components/shell";
import { Banner, Card, Field } from "../components/ui";
import { Me, api } from "../lib/api";

export interface DigestSchedule {
  /** ISO weekday: 1 is Monday. */
  day: number; day_name: string;
  /** 0 to 23, in the practice's time zone. */
  hour: number;
  timezone: string;
  /** Whether the practice owner has kept or changed it at least once. */
  confirmed: boolean;
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
  const [form, setForm] = useState<{ day: number; hour: number; timezone: string } | null>(null);
  const [saved, setSaved] = useState(false);
  useEffect(() => {
    if (schedule.data) {
      setForm({ day: schedule.data.day, hour: schedule.data.hour,
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
    || form.timezone !== now.timezone;
  const others = everyZone().filter((z) => !COMMON_ZONES.some(([id]) => id === z));
  const listed = COMMON_ZONES.some(([id]) => id === form.timezone)
    || others.includes(form.timezone);
  const set = (change: Partial<typeof form>) => { setForm({ ...form, ...change }); setSaved(false); };

  return (
    <>
      <PageHead title="Digests"
        sub="When the progress digests your clients' stakeholders receive are sent." />
      <Card title="Digest day and time">
        <p className="small" style={{ marginTop: 0 }}>
          Digests go out on <strong>{scheduleSentence(now)}</strong>.
        </p>
        <div className="row">
          <Field label="Day">
            <select aria-label="Digest day" value={form.day}
              onChange={(e) => set({ day: Number(e.target.value) })}>
              {DAYS.map((name, index) => <option key={name} value={index + 1}>{name}</option>)}
            </select>
          </Field>
          <Field label="Time">
            <select aria-label="Digest time" value={form.hour}
              onChange={(e) => set({ hour: Number(e.target.value) })}>
              {Array.from({ length: 24 }, (_, hour) => (
                <option key={hour} value={hour}>{hourLabel(hour)}</option>
              ))}
            </select>
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
        {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
        {saved && <Banner kind="ok">Saved. Digests now go out on {scheduleSentence(now)}.</Banner>}
        <button className="primary" disabled={!changed || save.isPending}
          onClick={() => save.mutate()}>
          {save.isPending ? "Saving…" : "Save"}
        </button>

        <ul className="small muted" style={{ marginBottom: 0 }}>
          <li><strong>Weekly</strong> digests are written 24 hours before this time, so there
            is a day to read and approve them, and sent at this time.</li>
          <li><strong>Monthly</strong> digests go on the first {DAYS[form.day - 1]} of the
            month and cover the month before.</li>
          <li>A stakeholder set to <strong>every update</strong> is not on this schedule: that
            digest is sent as soon as it is approved.</li>
          <li>A change applies to digests written from now on. One already waiting on
            the <Link to="/digests">Digests</Link> screen keeps the time it was written
            with.</li>
          <li>The time zone is the practice's: it also sets the local hour of the app's
            other daily jobs.</li>
          <li>Nothing here sends a digest. Every digest still waits for the practice owner
            or an associate to approve it.</li>
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

  return (
    <Card title="When should your digests go out?">
      <p style={{ marginTop: 0 }}>
        They are set to go out on <strong>{scheduleSentence(schedule.data)}</strong>. Weekly
        digests are written the day before so you have time to approve them.
      </p>
      <div className="row tight">
        <button className="primary" disabled={keep.isPending} onClick={() => keep.mutate()}>
          Keep {DAYS[schedule.data.day - 1]}s at {hourLabel(schedule.data.hour)}
        </button>
        <Link className="button" to="/settings/digests">Change the day or time</Link>
      </div>
      <p className="small muted" style={{ marginBottom: 0 }}>
        You can change this later in Settings → Digests.
      </p>
    </Card>
  );
}
