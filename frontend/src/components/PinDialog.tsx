import { useState } from "react";

import { NoteFull, api } from "../lib/api";
import { Banner, Field } from "./ui";

const PIN = /^\d{4,6}$/;

/**
 * FR-2.11a and FR-2.13, in the one place a PIN is set.
 *
 * An auto-derived title IS the first line of the body, and the title is what
 * a locked note still shows. So on an auto-titled note this dialog will not
 * take a PIN until a real title has been typed, and it says why.
 */
export function PinDialog({ note, onDone, onCancel }: {
  note: NoteFull; onDone: (n: NoteFull) => void; onCancel: () => void;
}) {
  const needsTitle = note.title_is_auto;
  const [title, setTitle] = useState("");
  const [pin, setPin] = useState("");
  const [again, setAgain] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);

  const titleOk = !needsTitle || (title.trim() && title.trim() !== note.title.trim());
  const pinOk = PIN.test(pin) && pin === again;

  async function submit() {
    setBusy(true);
    setError("");
    try {
      if (needsTitle) await api.patch(`/api/notes/${note.id}/`, { title: title.trim() });
      onDone(await api.post<NoteFull>(`/api/notes/${note.id}/pin/`, { pin }));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="card" role="dialog" aria-label={note.is_locked ? "Change PIN" : "Set a PIN"}>
      <h3 style={{ marginTop: 0 }}>{note.is_locked ? "Change this note's PIN" : "Put a PIN on this note"}</h3>
      <p className="small">
        A PIN hides this note from other people using the app: they see its title and what it
        is linked to, and nothing else. <strong>It is a privacy screen, not encryption.</strong>{" "}
        It does not hide the note from the founder fractional (who can reset it), from a
        database export, or from the nightly backup.
      </p>

      {needsTitle && (
        <>
          <Banner kind="warn">
            <strong>Type a title first.</strong> This note has no title of its own, so it is
            using its first line — <em>“{note.title}”</em>. A locked note still shows its title,
            so that line would stay visible to everyone. Choose a title that does not give the
            content away.
          </Banner>
          <Field label="Title shown on the locked note">
            <input aria-label="Title shown on the locked note" value={title}
              onChange={(e) => setTitle(e.target.value)} placeholder="e.g. HR matter" />
          </Field>
        </>
      )}

      <div className="row">
        <Field label="PIN (4–6 digits)">
          <input aria-label="PIN" type="password" inputMode="numeric" autoComplete="new-password"
            value={pin} onChange={(e) => setPin(e.target.value)} disabled={!titleOk} />
        </Field>
        <Field label="Same PIN again">
          <input aria-label="Confirm PIN" type="password" inputMode="numeric" autoComplete="new-password"
            value={again} onChange={(e) => setAgain(e.target.value)} disabled={!titleOk} />
        </Field>
      </div>
      {pin && !PIN.test(pin) && <p className="small muted">A PIN is 4 to 6 digits.</p>}
      {error && <Banner kind="bad">{error}</Banner>}
      <div className="row">
        <button className="primary" disabled={!titleOk || !pinOk || busy} onClick={submit}>
          {note.is_locked ? "Change PIN" : "Set PIN"}
        </button>
        <button className="ghost" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
