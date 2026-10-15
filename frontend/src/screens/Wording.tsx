import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { useLocation } from "react-router-dom";

import { Banner, Card } from "../components/ui";
import { api } from "../lib/api";
import { DEFAULT_WORD_PAIRS, WORD_KINDS, WordPairs, cap, makeWords } from "../lib/words";

interface WordsData { words: WordPairs; defaults: WordPairs }

/**
 * Settings → Branding → Wording (2026-10-15, from Melissa's feedback; a
 * section of Branding, not a page of its own, since Bryan's ruling the same
 * day). What this practice calls a goal, a project, a task and a step,
 * singular and plural. They show wherever the practice and its clients read
 * them; changing one moves no data and re-sends nothing. An emptied pair goes
 * back to the default. Getting started links here as `#wording`.
 */
export function WordingSection() {
  const qc = useQueryClient();
  const data = useQuery<WordsData>({
    queryKey: ["words-settings"], queryFn: () => api.get<WordsData>("/api/settings/words") });
  const [form, setForm] = useState<WordPairs | null>(null);
  const [note, setNote] = useState<{ kind: string; text: string } | null>(null);
  useEffect(() => { if (data.data && form === null) setForm(data.data.words); },
    [data.data, form]);
  // Reached from Getting started: brought into view once it has drawn.
  const { hash } = useLocation();
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (form && hash === "#wording") box.current?.scrollIntoView?.({ block: "start" });
  }, [form !== null, hash]); // eslint-disable-line react-hooks/exhaustive-deps

  const save = useMutation({
    mutationFn: (words: WordPairs) => api.put<WordsData>("/api/settings/words", { words }),
    onSuccess: (saved) => {
      qc.setQueryData(["words-settings"], saved);
      setForm(saved.words);
      qc.invalidateQueries({ queryKey: ["me"] });
      setNote({ kind: "ok", text: "Saved. The new words show from now on; nothing else changed." });
    },
    onError: (e: Error) => setNote({ kind: "bad", text: e.message }),
  });

  if (!form) return null;
  const sample = makeWords(form);
  const set = (kind: keyof WordPairs, part: "singular" | "plural", value: string) =>
    setForm({ ...form, [kind]: { ...form[kind], [part]: value } });

  return (
    <div id="wording" ref={box}>
      <Card title="Wording">
        {note && <Banner kind={note.kind}>{note.text}</Banner>}
        <p className="small muted" style={{ marginTop: 0 }}>
          What your practice calls the four levels of its work. They show on every screen,
          in the portal, in digests, emails and PDFs.
        </p>
        <table>
          <thead><tr><th>Level</th><th>One</th><th>More than one</th></tr></thead>
          <tbody>
            {WORD_KINDS.map((kind) => (
              <tr key={kind}>
                <td>{cap(DEFAULT_WORD_PAIRS[kind].singular)}
                  <div className="when">default: {DEFAULT_WORD_PAIRS[kind].singular} /
                    {" "}{DEFAULT_WORD_PAIRS[kind].plural}</div></td>
                <td><input aria-label={`Word for one ${DEFAULT_WORD_PAIRS[kind].singular}`}
                  maxLength={30} value={form[kind].singular}
                  onChange={(e) => set(kind, "singular", e.target.value)} /></td>
                <td><input aria-label={`Word for more than one ${DEFAULT_WORD_PAIRS[kind].singular}`}
                  maxLength={30} value={form[kind].plural}
                  onChange={(e) => set(kind, "plural", e.target.value)} /></td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="small muted" aria-label="How it reads">
          Reads as: {sample.Goals} hold {sample.projects}, {sample.projects} hold
          {" "}{sample.tasks}, and {sample.aTask} can have {sample.steps}.
        </p>
        <p className="small muted">
          Changing a word changes what is shown from now on. No {sample.goal}, {sample.project},
          {" "}{sample.task} or {sample.step} moves, and nothing already sent is sent again.
        </p>
        <div className="row tight">
          <button className="primary" disabled={save.isPending}
            onClick={() => save.mutate(form)}>Save the wording</button>
          <button className="ghost" disabled={save.isPending}
            onClick={() => setForm(data.data!.defaults)}>Back to the defaults</button>
        </div>
      </Card>
    </div>
  );
}
