import { useEffect, useRef, useState } from "react";

import { api } from "../lib/api";
import { Banner } from "./ui";

/** FR-2.14 — soft cap 120 minutes, warning at 110. Mirrors the server. */
export const MAX_SECONDS = 120 * 60;
export const WARN_AT_SECONDS = 110 * 60;

function pickMimeType(): string {
  const candidates = ["audio/webm;codecs=opus", "audio/ogg;codecs=opus"];
  const supported = typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported
    ? candidates.find((t) => MediaRecorder.isTypeSupported(t))
    : undefined;
  return supported ?? candidates[0];
}

export function clock(seconds: number) {
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = Math.floor(seconds % 60);
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
           : `${m}:${String(s).padStart(2, "0")}`;
}

type Phase = "idle" | "consent" | "recording" | "stopping";

/**
 * Browser recording. The consent reminder (FR-2.15) is shown before the first
 * recording of each sign-in session; confirming it dismisses it for that
 * session, and the server — not this browser — remembers, so signing out
 * brings it back.
 */
export function Recorder({ onComplete, onCancel, onActiveChange }: {
  onComplete: (blob: Blob, seconds: number, cappedAt120: boolean) => void;
  onCancel?: () => void;
  /** True from the consent prompt until the audio is handed over. */
  onActiveChange?: (active: boolean) => void;
}) {
  const [phase, setPhase] = useState<Phase>("idle");
  useEffect(() => { onActiveChange?.(phase !== "idle"); }, [phase, onActiveChange]);
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState("");
  const recorder = useRef<MediaRecorder | null>(null);
  const stream = useRef<MediaStream | null>(null);
  const chunks = useRef<Blob[]>([]);
  const startedAt = useRef(0);
  const ticker = useRef<ReturnType<typeof setInterval> | null>(null);
  const capped = useRef(false);

  useEffect(() => () => {
    if (ticker.current) clearInterval(ticker.current);
    stream.current?.getTracks().forEach((t) => t.stop());
  }, []);

  async function requestStart() {
    setError("");
    try {
      const reminder = await api.get<{ dismissed: boolean }>("/api/notes/consent-reminder/");
      if (!reminder.dismissed) { setPhase("consent"); return; }
    } catch {
      setPhase("consent"); // when in doubt, remind
      return;
    }
    await begin();
  }

  async function confirmConsent() {
    await api.post("/api/notes/consent-reminder/").catch(() => undefined);
    await begin();
  }

  async function begin() {
    try {
      stream.current = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      setPhase("idle");
      setError("The browser was not allowed to use the microphone.");
      return;
    }
    const type = pickMimeType();
    const rec = new MediaRecorder(stream.current, { mimeType: type, audioBitsPerSecond: 32000 });
    chunks.current = [];
    capped.current = false;
    rec.ondataavailable = (e) => { if (e.data && e.data.size) chunks.current.push(e.data); };
    rec.onstop = () => {
      if (ticker.current) clearInterval(ticker.current);
      stream.current?.getTracks().forEach((t) => t.stop());
      const seconds = Math.min(MAX_SECONDS, Math.round((Date.now() - startedAt.current) / 1000));
      const blob = new Blob(chunks.current, { type: rec.mimeType || type });
      setPhase("idle");
      setElapsed(0);
      onComplete(blob, seconds, capped.current);
    };
    recorder.current = rec;
    startedAt.current = Date.now();
    // A chunk every 10 s, so a crash mid-call loses seconds, not the call.
    rec.start(10_000);
    setPhase("recording");
    ticker.current = setInterval(() => {
      const seconds = (Date.now() - startedAt.current) / 1000;
      setElapsed(seconds);
      if (seconds >= MAX_SECONDS && rec.state === "recording") {
        capped.current = true;
        stop();
      }
    }, 1000);
  }

  function stop() {
    if (recorder.current && recorder.current.state === "recording") {
      setPhase("stopping");
      recorder.current.stop();
    }
  }

  if (phase === "consent") {
    return (
      <div className="card" role="alertdialog" aria-label="Recording consent">
        <p style={{ marginTop: 0 }}>
          <strong>Before you record, tell everyone on the call and confirm they agree.</strong>{" "}
          Recording a conversation without the other people's consent can be unlawful,
          depending on where you and they are.
        </p>
        <div className="row">
          <button className="primary" onClick={confirmConsent}>Everyone has agreed — start recording</button>
          <button className="ghost" onClick={() => { setPhase("idle"); onCancel?.(); }}>Cancel</button>
        </div>
        <p className="muted small">You will not be asked again until you next sign in.</p>
      </div>
    );
  }

  if (phase === "recording" || phase === "stopping") {
    const warn = elapsed >= WARN_AT_SECONDS;
    return (
      <div className="card" aria-live="polite">
        <div className="spread">
          <span><span className="pill bad">● REC</span> <span className="mono">{clock(elapsed)}</span></span>
          <button className="danger" onClick={stop} disabled={phase === "stopping"}>Stop recording</button>
        </div>
        {warn && (
          <Banner kind="warn">
            {clock(Math.max(0, MAX_SECONDS - elapsed))} left. Recording stops automatically at
            120 minutes and everything captured so far is kept.
          </Banner>
        )}
      </div>
    );
  }

  return (
    <>
      <button onClick={requestStart}>● Record</button>
      {error && <Banner kind="bad">{error}</Banner>}
    </>
  );
}
