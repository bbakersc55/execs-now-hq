import { useMutation } from "@tanstack/react-query";
import { CalendarPlus } from "lucide-react";
import { useState } from "react";

import { api } from "../lib/api";
import { Banner } from "./ui";

export type CalendarSource = "task" | "follow_up" | "stage_rule";

/**
 * "Add to calendar" (2026-10-27): a day, a time and a length, then an event on
 * the person's own calendar. Nobody is invited: the event is theirs.
 * `open` starts it unfolded, for a stage rule's question on a move.
 */
export function AddToCalendar({ source, sourceId, contact, date, title, minutes = 30,
  open: startOpen = false, label = "Add to calendar", onDone, onCancel }: {
  source: CalendarSource; sourceId: string; contact?: string; date?: string | null;
  title: string; minutes?: number; open?: boolean; label?: string;
  onDone?: (said: string) => void; onCancel?: () => void;
}) {
  const [open, setOpen] = useState(startOpen);
  const [day, setDay] = useState(date || new Date().toISOString().slice(0, 10));
  const [time, setTime] = useState("09:00");
  const [length, setLength] = useState(minutes);
  const [name, setName] = useState(title);
  const [problem, setProblem] = useState("");
  const [done, setDone] = useState("");

  const add = useMutation({
    mutationFn: () => api.post<{ web_link: string; title: string }>("/api/calendar/add/", {
      source, source_id: sourceId, contact, date: day, time, minutes: length, title: name }),
    onSuccess: (made) => {
      const said = `“${made.title}” is on your calendar, ${day} at ${time}.`;
      setDone(said); setProblem(""); setOpen(false);
      onDone?.(said);
    },
    onError: (e: Error) => setProblem(e.message),
  });

  if (!open) {
    return (
      <span className="add-to-calendar">
        <button className="ghost small" onClick={() => { setOpen(true); setDone(""); }}>
          <CalendarPlus size={14} /> {label}
        </button>
        {done && <span className="small muted"> {done}</span>}
      </span>
    );
  }
  return (
    <div className="add-to-calendar open" role="group" aria-label={label}>
      <div className="row tight wrap">
        <input aria-label="Event title" value={name} onChange={(e) => setName(e.target.value)}
          style={{ flex: "1 1 14rem" }} />
        <input aria-label="Day" type="date" value={day} onChange={(e) => setDay(e.target.value)} />
        <input aria-label="Time" type="time" value={time} onChange={(e) => setTime(e.target.value)} />
        <select aria-label="Length" value={length} onChange={(e) => setLength(Number(e.target.value))}>
          {[15, 30, 45, 60, 90].map((m) => <option key={m} value={m}>{m} minutes</option>)}
        </select>
      </div>
      {problem && <Banner kind="bad">{problem}</Banner>}
      <div className="row tight wrap">
        <button className="primary small" disabled={add.isPending || !day || !time || !name.trim()}
          onClick={() => add.mutate()}>{add.isPending ? "Adding…" : "Add it"}</button>
        <button className="ghost small" onClick={() => { setOpen(false); onCancel?.(); }}>
          {onCancel ? "Not now" : "Cancel"}</button>
      </div>
    </div>
  );
}
