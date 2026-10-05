import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { PageHead } from "../components/shell";
import { Banner, Card, Field } from "../components/ui";
import { NotesSettings, api } from "../lib/api";

/**
 * Settings, Notes section (UI 3 spec §4). It was a card at the bottom of the
 * Notes screen; the card, its wording and its warning are unchanged.
 */
export function NotesSettingsPage() {
  return (
    <>
      <PageHead title="Notes" sub="How long recordings are kept." />
      <RecordingSettings />
    </>
  );
}

function RecordingSettings() {
  const qc = useQueryClient();
  const settings = useQuery<NotesSettings>({
    queryKey: ["notes-settings"], queryFn: () => api.get<NotesSettings>("/api/notes/settings/"),
  });
  const [days, setDays] = useState<string | null>(null);
  const save = useMutation({
    mutationFn: () => api.patch<NotesSettings>("/api/notes/settings/", { audio_retention_days: Number(days) }),
    onSuccess: () => { setDays(null); qc.invalidateQueries({ queryKey: ["notes-settings"] }); },
  });
  const value = days ?? String(settings.data?.audio_retention_days ?? "");

  return (
    <Card title="Recording audio retention">
      <p className="small">
        Transcripts and summaries are kept indefinitely. The audio itself is deleted this many
        days after recording — but only once it has been transcribed. Audio that never
        transcribed is kept, and flagged on its note, until someone retries or discards it.
      </p>
      <Field label="Keep audio for (days)">
        <input aria-label="Keep audio for (days)" type="number" min={0} value={value}
          onChange={(e) => setDays(e.target.value)} style={{ maxWidth: "8rem" }} />
      </Field>
      {value === "0" && (
        <Banner kind="warn">
          At 0, audio is deleted as soon as its transcript is made. <strong>A recording can then
          never be transcribed again</strong> — if the transcript is poor, there is nothing to retry.
        </Banner>
      )}
      {save.isError && <Banner kind="bad">{(save.error as Error).message}</Banner>}
      <button className="primary" disabled={days === null || save.isPending} onClick={() => save.mutate()}>Save</button>
    </Card>
  );
}
