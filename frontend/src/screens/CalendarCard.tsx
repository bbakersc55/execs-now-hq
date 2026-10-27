import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { Banner, Card, Pill, when } from "../components/ui";
import { CalendarStatus, api } from "../lib/api";

/**
 * Profile → Your calendar (2026-10-27): each person on the practice's team
 * connects their own, Google Calendar or Microsoft 365 by the practice's
 * provider. One calendar a person. On Profile rather than Settings: it is
 * personal, like browser notifications, and an assistant has no Settings.
 * What the app reads and keeps is said here, before consent.
 */
export function CalendarCard() {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");

  useEffect(() => {
    const connected = params.get("calendar_connected");
    const error = params.get("calendar_error");
    if (connected) setNote(`Connected ${connected}. Home shows today's and tomorrow's meetings.`);
    if (error) setProblem(error);
    if (connected || error) {
      setParams({}, { replace: true });
      qc.invalidateQueries({ queryKey: ["calendar"] });
    }
  }, [params, setParams, qc]);

  const status = useQuery<CalendarStatus>({
    queryKey: ["calendar"], queryFn: () => api.get<CalendarStatus>("/api/calendar/"),
  });
  const start = useMutation({
    mutationFn: () => api.post<{ authorization_url: string }>("/api/calendar/start/"),
    onSuccess: (d) => { window.location.href = d.authorization_url; },
    onError: (e: Error) => setProblem(e.message),
  });
  const sync = useMutation({
    mutationFn: () => api.post<CalendarStatus>("/api/calendar/sync/"),
    onSuccess: (d) => {
      qc.setQueryData(["calendar"], d);
      qc.invalidateQueries({ queryKey: ["calendar-upcoming"] });
      if (d.last_error) { setProblem(d.last_error); setNote(""); }
      else { setNote("Read again just now."); setProblem(""); }
    },
    onError: (e: Error) => setProblem(e.message),
  });
  const disconnect = useMutation({
    mutationFn: () => api.post<CalendarStatus>("/api/calendar/disconnect/"),
    onSuccess: (d) => {
      qc.setQueryData(["calendar"], d);
      qc.invalidateQueries({ queryKey: ["calendar-upcoming"] });
      setNote("Disconnected. The stored token and the meetings read from it were removed.");
      setProblem("");
    },
    onError: (e: Error) => setProblem(e.message),
  });

  if (status.isLoading) return <p className="muted">Loading…</p>;
  if (status.isError) return <Banner kind="bad">{(status.error as Error).message}</Banner>;
  const s = status.data!;
  const busy = start.isPending || sync.isPending || disconnect.isPending;

  return (
    <section id="calendar">
      {note && <Banner kind="ok">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}
      {s.refusal && <Banner kind="info">{s.refusal}</Banner>}
      {!s.configured && !s.refusal && (
        <Banner kind="warn">{s.provider_label} isn't set up on this server yet, so there is no
          calendar to connect. Contact support.</Banner>
      )}
      <Card title="Your calendar"
        actions={s.connected ? (
          <>
            <button className="ghost" disabled={busy} onClick={() => sync.mutate()}>
              {sync.isPending ? "Reading…" : "Read it now"}</button>
            <button className="danger" disabled={busy} onClick={() => disconnect.mutate()}>
              Disconnect</button>
          </>
        ) : (
          <button className="primary" disabled={busy || !s.configured || !!s.refusal}
            onClick={() => start.mutate()}>Connect your calendar</button>
        )}>
        <p className="small muted" style={{ marginTop: 0 }}>
          Home shows today's and tomorrow's meetings from it, matched to your contacts and
          companies. {s.provider_label}, as the practice's mail.</p>
        {s.connected ? (
          <>
            <p className="wrap-anywhere"><Pill kind="ok">connected</Pill> {s.email_address}</p>
            <p className="muted small">
              {s.last_synced_at ? `Last read ${when(s.last_synced_at)}.` : "Not read yet."}
              {" "}Read every fifteen minutes, a day back and two weeks ahead.
            </p>
            {s.last_error && <Banner kind="bad">{s.last_error}</Banner>}
          </>
        ) : !s.refusal && (
          <p><Pill kind="warn">not connected</Pill> No calendar is connected for you.</p>
        )}
        <div className="small muted">
          <p style={{ marginBottom: ".25rem" }}><strong>What the app reads and keeps</strong></p>
          <ul style={{ marginTop: 0 }}>
            <li>Each meeting's title, time and link, from a day back to two weeks ahead.
              Private and cancelled meetings are left out.</li>
            <li>Attendees' email addresses, only to match your contacts and companies.
              The addresses are not kept, only the matches.</li>
            <li><strong>Never a meeting's description or notes</strong>: they are not read, so
              nothing of them can reach Claude.</li>
            <li>It adds events only when you press Add to calendar, and invites nobody.</li>
          </ul>
          <p style={{ marginTop: 0 }}>
            {s.provider === "microsoft"
              ? "Microsoft asks for permission to read and write your calendar (Calendars.ReadWrite)."
              : "Google asks for permission to see and edit events on your calendars (calendar.events)."}
          </p>
        </div>
      </Card>
    </section>
  );
}
