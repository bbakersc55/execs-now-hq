import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import React, { useEffect, useState } from "react";

import { Field } from "../components/ui";
import { api } from "../lib/api";

/** GET/PATCH {session}/document-words/ (apps/strategy/document.py `represent`). */
export interface Bullet { text: string; owner: string }
export interface DocPath {
  side: "a" | "b"; title: string; blurb: string; for: string[]; against: string[];
}
export interface DocComponent { key: string; name: string; pill: string; line: string }
export interface Move { lead: string; rest: string }
export interface Words {
  headline: string; intro: string;
  tile: { number: string; label: string };
  mirror_headline: string; mirror_body: string; working: string; not_yet: string;
  components: DocComponent[];
  boxes: Record<"30" | "60" | "90", Bullet[]>;
  paths: DocPath[];
  recommended: "" | "a" | "b";
  next_moves: Move[];
  closing: string; email: string; website: string;
}
/** The sign-off band's lines: Settings → Branding's, unless the document has
 * its own (2026-10-17). */
export type SignKey = "closing" | "email" | "website";
export type SignOff = Record<SignKey, string>;
export interface DocumentWordsData {
  words: Words;
  saved: Partial<Words>;
  proposed: Partial<Words>;
  signoff: { branding: SignOff; own: Partial<SignOff> };
  limits: Record<string, number>;
  most: Record<string, number>;
  hidden: string[];
  tiles: { number: string; label: string }[];
  box_dates: Record<string, string>;
  full_pages?: number[];
}

const HORIZONS = ["30", "60", "90"] as const;
const SIGN_KEYS: SignKey[] = ["closing", "email", "website"];
const SIGN_LABEL: Record<SignKey, string> = {
  closing: "Closing line", email: "Email under it", website: "Website under it",
};

/** null: the line is Branding's. A string, even empty, is being rewritten here. */
type Own = Record<SignKey, string | null>;
function ownOf(data: DocumentWordsData): Own {
  const own = data.signoff?.own ?? {};
  return { closing: own.closing ?? null, email: own.email ?? null,
           website: own.website ?? null };
}

/** Claude's draft over the words as they stand: only the parts it wrote. */
function withDraft(words: Words, draft: Partial<Words>): Words {
  const out: Words = { ...words, ...draft } as Words;
  out.components = words.components.map((c) => {
    const drafted = (draft.components ?? []).find((d) => d.key === c.key);
    return drafted ? { ...c, ...Object.fromEntries(
      Object.entries(drafted).filter(([, v]) => v !== undefined && v !== "")) } : c;
  });
  out.paths = words.paths.map((p) => {
    const drafted = (draft.paths ?? []).find((d) => d.side === p.side);
    return drafted ? { ...p, ...drafted } : p;
  });
  if (draft.boxes) out.boxes = { ...words.boxes, ...draft.boxes };
  return out;
}

/** A line's count, shown only when the line is over its length. */
function Over({ text, most, label }: { text: string; most: number; label: string }) {
  if (text.length <= most) return null;
  return (
    <span className="tiny" role="status" aria-label={`${label} is over its length`}
      style={{ color: "var(--bad)" }}>
      {text.length} of {most}: {text.length - most} over
    </span>
  );
}

/** A line of the document. `label` names it for a screen reader and the
 * count; `shown`, when given, is the shorter label above the box. */
function Line({ label, value, most, onChange, rows, shown }: {
  label: string; value: string; most: number; onChange: (v: string) => void; rows?: number;
  shown?: string;
}) {
  return (
    <Field label={shown ?? label}>
      {rows ? (
        <textarea aria-label={`On the document: ${label}`} rows={rows} value={value}
          onChange={(e) => onChange(e.target.value)} />
      ) : (
        <input aria-label={`On the document: ${label}`} value={value}
          onChange={(e) => onChange(e.target.value)} />
      )}
      <Over text={value} most={most} label={label} />
    </Field>
  );
}

/** Columns that hold their widths, whatever each box holds. */
function Cols({ cols, children }: { cols: string; children: React.ReactNode }) {
  return (
    <div style={{ display: "grid", gridTemplateColumns: cols, gap: ".5rem",
                  alignItems: "start" }}>{children}</div>
  );
}

const REMOVE = { flex: "none", width: "auto", alignSelf: "center", marginTop: "1.1rem" };

/**
 * "Change the words on the document" (2026-10-15): every line the two-page
 * document prints, each held to its length. A line over its length shows its
 * count and the save waits until it is shortened, so the PDF never runs past
 * its page. Claude's draft is a proposal: "Use Claude's draft" puts it in the
 * boxes below, and nothing changes on the document until Save.
 */
export function DocumentWords({ path, setNote, onChanged }: {
  path: string; setNote: (text: string) => void; onChanged: () => void;
}) {
  const qc = useQueryClient();
  const url = `${path}document-words/`;
  const data = useQuery<DocumentWordsData>({ queryKey: ["document-words", path],
                                             queryFn: () => api.get(url) });
  const [form, setForm] = useState<Words | null>(null);
  const [own, setOwn] = useState<Own | null>(null);
  const [dirty, setDirty] = useState(false);
  useEffect(() => {
    if (data.data && (form === null || !dirty)) {
      setForm(data.data.words);
      setOwn(ownOf(data.data));
    }
  }, [data.data]); // eslint-disable-line react-hooks/exhaustive-deps

  const done = (fresh: DocumentWordsData, text: string) => {
    qc.setQueryData(["document-words", path], fresh);
    setForm(fresh.words);
    setOwn(ownOf(fresh));
    setDirty(false);
    setNote(text);
    onChanged();
  };
  const save = useMutation({
    mutationFn: (body: object) => api.patch<DocumentWordsData>(url, body),
    onSuccess: (fresh, body) => done(fresh, "reset" in body
      ? "The document reads from the session again."
      : "Saved. The document has the new words."),
    onError: (e: Error) => setNote(e.message),
  });
  const draft = useMutation({
    mutationFn: () => api.post<DocumentWordsData>(`${path}draft-document-words/`, {}),
    onSuccess: (fresh) => {
      qc.setQueryData(["document-words", path], fresh);
      setNote("Claude drafted the words. Use them below, change what you like, and save.");
    },
    onError: (e: Error) => setNote(e.message),
  });

  if (!data.data || !form || !own) return null;
  const { limits: L, most, hidden, proposed } = data.data;
  const fromBranding = data.data.signoff?.branding
    ?? { closing: form.closing, email: form.email, website: form.website };
  const setSign = (key: SignKey, value: string | null) => {
    setOwn({ ...own, [key]: value });
    setDirty(true);
  };
  /** What the editor saves: every line but the sign-off's, and of the
   * sign-off only the lines rewritten here. */
  const body = () => {
    const { closing: _c, email: _e, website: _w, ...rest } = form;
    void _c; void _e; void _w;
    return { ...rest, signoff: Object.fromEntries(
      SIGN_KEYS.filter((k) => own[k] !== null).map((k) => [k, own[k]])) };
  };
  const show = (part: string) => !hidden.includes(part);
  const set = (patch: Partial<Words>) => { setForm({ ...form, ...patch }); setDirty(true); };
  const hasDraft = Object.keys(proposed ?? {}).length > 0;

  const over = [
    form.headline.length > L.headline, form.intro.length > L.intro,
    form.tile.number.length > L.tile_number, form.tile.label.length > L.tile_label,
    form.mirror_headline.length > L.mirror_headline,
    form.mirror_body.length > L.mirror_body, form.working.length > L.working,
    form.not_yet.length > L.not_yet,
    ...SIGN_KEYS.map((k) => (own[k] ?? "").length > L[k]),
    ...form.components.flatMap((c) => [c.name.length > L.component_name,
                                       c.line.length > L.component_line]),
    ...HORIZONS.flatMap((h) => form.boxes[h].flatMap((b) => [
      b.text.length > L.bullet, b.owner.length > L.owner])),
    ...form.paths.flatMap((p) => [p.title.length > L.path_title,
      p.blurb.length > L.path_blurb,
      ...[...p.for, ...p.against].map((x) => x.length > L.path_point)]),
    ...form.next_moves.map((m) => moveLength(m) > L.next_move),
  ].filter(Boolean).length;

  const setBox = (h: typeof HORIZONS[number], bullets: Bullet[]) =>
    set({ boxes: { ...form.boxes, [h]: bullets } });
  const setPath = (side: string, patch: Partial<DocPath>) =>
    set({ paths: form.paths.map((p) => (p.side === side ? { ...p, ...patch } : p)) });

  const full = data.data.full_pages ?? [];
  return (
    <>
    {full.length > 0 && (
      <p className="small" role="alert" style={{ color: "var(--bad)", margin: ".75rem 0 0" }}>
        {full.map((n) => `Page ${n}`).join(" and ")} of the document{" "}
        {full.length === 1 ? "runs" : "run"} past the foot. Shorten a few of{" "}
        {full.length === 1 ? "its" : "their"} lines below; it will not send until it fits.
      </p>
    )}
    <details className="document-words" style={{ marginTop: ".75rem" }}>
      <summary><strong className="small">Change the words on the document</strong></summary>
      <p className="small muted">
        Every line here is on the document, and each has a length so the two pages hold.
        A line over its length shows a count; shorten it to save.
      </p>
      <div className="row tight">
        <button className="small" disabled={draft.isPending} onClick={() => draft.mutate()}>
          {draft.isPending ? "Drafting…" : "Draft the words with Claude"}
        </button>
        {hasDraft && (
          <button className="small" onClick={() => set(withDraft(form, proposed))}>
            Use Claude's draft
          </button>
        )}
        {Object.keys(data.data.saved ?? {}).length > 0 && (
          <button className="link small" disabled={save.isPending}
            onClick={() => save.mutate({ reset: true })}>
            Back to the session's own words
          </button>
        )}
      </div>

      <Line label="Headline" value={form.headline} most={L.headline}
        onChange={(v) => set({ headline: v })} />
      <Line label="Intro line" value={form.intro} most={L.intro}
        onChange={(v) => set({ intro: v })} />
      {show("map") && (
        <Cols cols="8rem 1fr">
          <Line label="First tile: the figure" value={form.tile.number} most={L.tile_number}
            onChange={(v) => set({ tile: { ...form.tile, number: v } })} />
          <Line label="First tile: what it counts" value={form.tile.label} most={L.tile_label}
            onChange={(v) => set({ tile: { ...form.tile, label: v } })} />
        </Cols>
      )}
      <p className="tiny muted" style={{ margin: 0 }}>
        The other tiles are worked out from the session:{" "}
        {data.data.tiles.slice(form.tile.number ? 1 : 0)
          .map((t) => `${t.number} ${t.label}`).join("; ") || "none yet"}.
      </p>

      {show("mirror") && (
        <>
          <p className="small" style={{ margin: ".75rem 0 0" }}><strong>The mirror</strong></p>
          <Line label="Mirror headline" value={form.mirror_headline} most={L.mirror_headline}
            onChange={(v) => set({ mirror_headline: v })} />
          <Line label="Mirror, up to three sentences" value={form.mirror_body}
            most={L.mirror_body} rows={3} onChange={(v) => set({ mirror_body: v })} />
          <Cols cols="1fr 1fr">
            <Line label="Working" value={form.working} most={L.working}
              onChange={(v) => set({ working: v })} />
            <Line label="Not yet" value={form.not_yet} most={L.not_yet}
              onChange={(v) => set({ not_yet: v })} />
          </Cols>
        </>
      )}

      {show("ratings") && form.components.length > 0 && (
        <>
          <p className="small" style={{ margin: ".75rem 0 0" }}><strong>The components</strong></p>
          {form.components.map((c, i) => (
            <Cols cols="10rem 7rem 1fr" key={c.key}>
              <Line label={`Component ${i + 1}`} value={c.name} most={L.component_name}
                onChange={(v) => set({ components: form.components.map((x) =>
                  (x.key === c.key ? { ...x, name: v } : x)) })} />
              <Field label="Pill">
                <select aria-label={`On the document: ${c.name} pill`} value={c.pill}
                  onChange={(e) => set({ components: form.components.map((x) =>
                    (x.key === c.key ? { ...x, pill: e.target.value } : x)) })}>
                  <option value="strong">Strong</option>
                  <option value="watch">Watch</option>
                  <option value="fix">Fix</option>
                </select>
              </Field>
              <Line label={`${c.name}: one line`} shown="One line" value={c.line}
                most={L.component_line}
                onChange={(v) => set({ components: form.components.map((x) =>
                  (x.key === c.key ? { ...x, line: v } : x)) })} />
            </Cols>
          ))}
        </>
      )}

      {show("map") && (
        <>
          <p className="small" style={{ margin: ".75rem 0 0" }}><strong>The map</strong></p>
          {HORIZONS.map((h) => (
            <div key={h} style={{ marginBottom: ".5rem" }}>
              <p className="small" style={{ margin: ".25rem 0" }}>
                Day {h} · {data.data!.box_dates[h]}
              </p>
              {form.boxes[h].map((b, i) => (
                <Cols cols="1fr 9rem auto" key={i}>
                  <Line label={`Day ${h}, bullet ${i + 1}`} shown={`Bullet ${i + 1}`}
                    value={b.text} most={L.bullet}
                    onChange={(v) => setBox(h, form.boxes[h].map((x, j) =>
                      (j === i ? { ...x, text: v } : x)))} />
                  <Line label={`Day ${h}, bullet ${i + 1}: owner`} shown="Owner" value={b.owner}
                    most={L.owner} onChange={(v) => setBox(h, form.boxes[h].map((x, j) =>
                      (j === i ? { ...x, owner: v } : x)))} />
                  <button className="link small" style={REMOVE}
                    aria-label={`Remove day ${h} bullet ${i + 1}`}
                    onClick={() => setBox(h, form.boxes[h].filter((_, j) => j !== i))}>
                    Remove
                  </button>
                </Cols>
              ))}
              {form.boxes[h].length < most.bullets && (
                <button className="link small"
                  onClick={() => setBox(h, [...form.boxes[h], { text: "", owner: "" }])}>
                  Add a bullet to day {h}
                </button>
              )}
            </div>
          ))}
        </>
      )}

      {show("paths") && form.paths.length > 0 && (
        <>
          <p className="small" style={{ margin: ".75rem 0 0" }}><strong>The two paths</strong></p>
          {form.paths.map((p) => (
            <div key={p.side} style={{ marginBottom: ".5rem" }}>
              <label className="inline small">
                <input type="radio" name="recommended" style={{ width: "auto" }}
                  aria-label={`Recommend path ${p.side.toUpperCase()}`}
                  checked={form.recommended === p.side}
                  onChange={() => set({ recommended: p.side })} />
                Recommended
              </label>
              <Cols cols="14rem 1fr">
                <Line label={`Path ${p.side.toUpperCase()}: title`} value={p.title}
                  most={L.path_title} onChange={(v) => setPath(p.side, { title: v })} />
                <Line label={`Path ${p.side.toUpperCase()}: one line`} value={p.blurb}
                  most={L.path_blurb} onChange={(v) => setPath(p.side, { blurb: v })} />
              </Cols>
              <Cols cols="1fr 1fr">
              {(["for", "against"] as const).map((side) => (
                <div key={side}>
                  {Array.from({ length: most.path_points }).map((_, i) => (
                    <Line key={i} value={p[side][i] ?? ""} most={L.path_point}
                      label={`Path ${p.side.toUpperCase()}: ${side === "for" ? "for" : "against"} ${i + 1}`}
                      shown={`${side === "for" ? "For" : "Against"} ${i + 1}`}
                      onChange={(v) => {
                        const points = [...p[side]];
                        points[i] = v;
                        setPath(p.side, { [side]: points.slice(0, most.path_points) });
                      }} />
                  ))}
                </div>
              ))}
              </Cols>
            </div>
          ))}
          {form.recommended && (
            <button className="link small" onClick={() => set({ recommended: "" })}>
              Recommend neither
            </button>
          )}
        </>
      )}

      <p className="small" style={{ margin: ".75rem 0 0" }}><strong>Before we meet again</strong></p>
      {form.next_moves.map((m, i) => (
        <Cols cols="14rem 1fr auto" key={i}>
          <Field label={`Next move ${i + 1}`}>
            <input aria-label={`On the document: next move ${i + 1}`} value={m.lead}
              placeholder="The action, in bold"
              onChange={(e) => set({ next_moves: form.next_moves.map((x, j) =>
                (j === i ? { ...x, lead: e.target.value } : x)) })} />
          </Field>
          <Field label="The detail">
            <input aria-label={`On the document: next move ${i + 1} detail`} value={m.rest}
              onChange={(e) => set({ next_moves: form.next_moves.map((x, j) =>
                (j === i ? { ...x, rest: e.target.value } : x)) })} />
            <Over text={moveText(m)} most={L.next_move}
              label={`Next move ${i + 1}`} />
          </Field>
          <button className="link small" style={REMOVE} aria-label={`Remove next move ${i + 1}`}
            onClick={() => set({ next_moves: form.next_moves.filter((_, j) => j !== i) })}>
            Remove
          </button>
        </Cols>
      ))}
      {form.next_moves.length < most.next_moves && (
        <button className="link small"
          onClick={() => set({ next_moves: [...form.next_moves, { lead: "", rest: "" }] })}>
          Add a next move
        </button>
      )}
      <p className="small" style={{ margin: ".75rem 0 0" }}><strong>The sign-off</strong></p>
      <p className="tiny muted" style={{ margin: 0 }}>
        The practice's, from Settings → Branding, unless you rewrite a line for this
        document here.
      </p>
      {SIGN_KEYS.map((k) => (
        <SignLine key={k} label={SIGN_LABEL[k]} most={L[k]} own={own[k]}
          branding={fromBranding[k]} onChange={(v) => setSign(k, v)} />
      ))}

      <div className="row tight" style={{ marginTop: ".5rem" }}>
        <button className="primary small" disabled={!dirty || over > 0 || save.isPending}
          onClick={() => save.mutate(body())}>Save these words</button>
        {over > 0 && <span className="small" style={{ color: "var(--bad)" }}>
          {over} line{over === 1 ? " is" : "s are"} over {over === 1 ? "its" : "their"} length.</span>}
        {dirty && over === 0 && <span className="small muted">Not saved yet: the document
          and the preview still have the old words.</span>}
      </div>
    </details>
    </>
  );
}

/** A sign-off line: Branding's, marked so, until it is rewritten here. */
function SignLine({ label, most, own, branding, onChange }: {
  label: string; most: number; own: string | null; branding: string;
  onChange: (v: string | null) => void;
}) {
  const value = own ?? branding;
  return (
    <Field label={label}>
      <input aria-label={`On the document: ${label}`} value={value}
        onChange={(e) => onChange(e.target.value)} />
      {own === null ? (
        <span className="tiny muted" aria-label={`${label} is from Branding`}>
          From Branding</span>
      ) : (
        <span className="tiny">
          {own === "" && <span className="muted">Empty: Branding's prints. </span>}
          <button className="link small" aria-label={`Use Branding's ${label.toLowerCase()}`}
            onClick={() => onChange(null)}>Use Branding's</button>
        </span>
      )}
      <Over text={own ?? ""} most={most} label={label} />
    </Field>
  );
}

/** As the server counts it: the lead, a space, and the detail. */
function moveText(m: Move): string {
  return m.rest ? `${m.lead} ${m.rest}` : m.lead;
}

function moveLength(m: Move): number {
  return moveText(m).length;
}
