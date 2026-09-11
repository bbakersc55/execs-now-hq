import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { clock } from "./Recorder";
import { Pending, listPending, retry } from "../lib/pendingUploads";
import { Banner } from "./ui";

/**
 * AC-2.8(b) — recordings this browser is still holding because an upload has
 * not been confirmed. Retried once on load; always offered for download, so
 * the audio is never trapped here either.
 */
export function PendingUploads() {
  const qc = useQueryClient();
  const [message, setMessage] = useState("");
  const pending = useQuery<Pending[]>({ queryKey: ["pending-uploads"], queryFn: listPending });

  async function retryAll(items: Pending[]) {
    const failures: string[] = [];
    for (const item of items) {
      const result = await retry(item.noteId);
      if (!result.ok) failures.push(result.reason);
    }
    setMessage(failures.length ? `Still not uploaded: ${failures[0]}` : "");
    qc.invalidateQueries({ queryKey: ["pending-uploads"] });
    qc.invalidateQueries({ queryKey: ["notes"] });
  }

  const items = pending.data ?? [];
  useEffect(() => {
    if (items.length) retryAll(items);
    // Once per load, not on every render.
  }, [items.length > 0]);

  if (!items.length) return null;
  return (
    <Banner kind="warn">
      <strong>{items.length} recording{items.length > 1 ? "s" : ""} waiting to upload</strong> —
      kept safely in this browser until the server confirms it has {items.length > 1 ? "them" : "it"}.
      {message && <> {message}</>}
      <ul className="small">
        {items.map((p) => (
          <li key={p.noteId}>
            <Link to={`/notes/${p.noteId}`}>{clock(p.durationSeconds)} recorded {new Date(p.savedAt).toLocaleString()}</Link>{" "}
            <a href={URL.createObjectURL(p.blob)} download={`recording-${p.noteId}.webm`}>download</a>
          </li>
        ))}
      </ul>
      <button onClick={() => retryAll(items)}>Retry upload now</button>
    </Banner>
  );
}
