import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { PageHead } from "../components/shell";
import { Banner, Card, Field, Pill, when } from "../components/ui";
import { api } from "../lib/api";
import { HEX, check, textOn } from "../lib/contrast";

/** GET /api/settings/branding (apps/tenancy/branding.py `current`). */
export interface BrandingSettings {
  display_name: string;
  practice_name: string;
  primary_color: string;
  accent_color: string;
  footer_text: string;
  has_logo: boolean;
  has_mark: boolean;
  branding_updated_at: string | null;
  defaults: { primary_color: string; accent_color: string };
}

interface Form {
  display_name: string;
  primary_color: string;
  accent_color: string;
  footer_text: string;
}

const FOOTER_MAX_LINES = 6;
const FOOTER_MAX_CHARS = 500;

/**
 * Settings → Branding (P1, owner 2026-10-02). The practice owner sets what
 * their clients see: the portal, every client-facing email and the PDFs.
 * Staff screens keep the product's own look. The server decides what saves;
 * this screen shows the same contrast rules as you choose.
 */
export function Branding() {
  const qc = useQueryClient();
  const [form, setForm] = useState<Form | null>(null);
  const [note, setNote] = useState("");
  const [problem, setProblem] = useState("");
  // Bumped after an upload so the preview images are fetched afresh.
  const [version, setVersion] = useState(0);

  const settings = useQuery<BrandingSettings>({
    queryKey: ["branding-settings"],
    queryFn: () => api.get<BrandingSettings>("/api/settings/branding"),
  });
  useEffect(() => {
    if (settings.data && form === null) {
      const s = settings.data;
      setForm({ display_name: s.display_name, primary_color: s.primary_color,
                accent_color: s.accent_color, footer_text: s.footer_text });
    }
  }, [settings.data, form]);

  const refreshed = (data: BrandingSettings, text: string) => {
    qc.setQueryData(["branding-settings"], data);
    qc.invalidateQueries({ queryKey: ["branding"] });
    setProblem("");
    setNote(text);
  };
  const failed = (e: Error) => { setNote(""); setProblem(e.message); };

  const save = useMutation({
    mutationFn: (body: Form) => api.put<BrandingSettings>("/api/settings/branding", body),
    onSuccess: (data) => refreshed(data, "Branding saved. Clients see it on their next page or email."),
    onError: failed,
  });
  const uploadImage = useMutation({
    mutationFn: ({ kind, file }: { kind: "logo" | "mark"; file: File }) => {
      const body = new FormData();
      body.append("file", file);
      return api.post<BrandingSettings>(`/api/settings/branding/${kind}`, body);
    },
    onSuccess: (data, { kind }) => {
      setVersion((v) => v + 1);
      refreshed(data, kind === "logo" ? "Logo uploaded." : "Mark uploaded.");
    },
    onError: failed,
  });
  const clearImage = useMutation({
    mutationFn: (kind: "logo" | "mark") =>
      api.del<BrandingSettings>(`/api/settings/branding/${kind}`),
    onSuccess: (data, kind) => {
      setVersion((v) => v + 1);
      refreshed(data, kind === "logo" ? "Logo removed." : "Mark removed; your initials show instead.");
    },
    onError: failed,
  });
  const reset = useMutation({
    mutationFn: () => api.post<BrandingSettings>("/api/settings/branding/reset"),
    onSuccess: (data) => {
      setVersion((v) => v + 1);
      setForm({ display_name: data.display_name, primary_color: data.primary_color,
                accent_color: data.accent_color, footer_text: data.footer_text });
      refreshed(data, "Back to the defaults: your practice name over neutral grays.");
    },
    onError: failed,
  });

  if (settings.isError) return <Banner kind="bad">{(settings.error as Error).message}</Banner>;
  if (!settings.data || !form) return <p className="muted">Loading…</p>;
  const s = settings.data;

  const colorsValid = HEX.test(form.primary_color) && HEX.test(form.accent_color);
  const checks = colorsValid ? check(form.primary_color, form.accent_color) : [];
  const blocked = checks.some((c) => c.blocks && !c.ok);
  const footerLines = form.footer_text.trim() ? form.footer_text.trim().split("\n").length : 0;
  const footerTooLong = footerLines > FOOTER_MAX_LINES || form.footer_text.length > FOOTER_MAX_CHARS;
  const set = (patch: Partial<Form>) => { setForm({ ...form, ...patch }); setNote(""); };

  return (
    <>
      <PageHead title="Branding"
        sub={<>What your clients see: the client portal, every email they get from you, and
          the PDFs. Your own team's screens keep the app's look.</>} />

      {note && <Banner kind="ok">{note}</Banner>}
      {problem && <Banner kind="bad">{problem}</Banner>}
      {!s.branding_updated_at && (
        <Banner kind="info">
          Not set yet. Until you save, clients see <strong>{s.practice_name}</strong> over
          neutral grays, with your initials as the mark.
        </Banner>
      )}

      <div className="row" style={{ alignItems: "flex-start", gap: "1.5rem", flexWrap: "wrap" }}>
        <div style={{ flex: "1 1 22rem", minWidth: 0 }}>
          <Card title="Name and colors">
            <Field label="Display name">
              <input aria-label="Display name" value={form.display_name} maxLength={80} placeholder={s.practice_name}
                onChange={(e) => set({ display_name: e.target.value })} />
            </Field>
            <ColorField label="Primary color" value={form.primary_color}
              onChange={(v) => set({ primary_color: v })} />
            <ColorField label="Accent color" value={form.accent_color}
              onChange={(v) => set({ accent_color: v })} />
            {colorsValid ? (
              <ul aria-label="Contrast" style={{ padding: 0, listStyle: "none" }}>
                {checks.map((c) => (
                  <li key={c.rule} className="small" style={{ margin: "0.25rem 0" }}>
                    <Pill kind={c.ok ? "ok" : c.blocks ? "bad" : "warn"}>
                      {c.ok ? "Passes" : c.blocks ? "Too low" : "Decoration only"}
                    </Pill>{" "}
                    {c.label}: {c.ratio.toFixed(2)} : 1 (needs {c.required})
                  </li>
                ))}
              </ul>
            ) : (
              <p className="small" style={{ color: "var(--bad)" }}>Use six-digit hex colors, like #0A3A65.</p>
            )}
            {checks.some((c) => !c.blocks && !c.ok) && (
              <p className="small muted">
                The accent is light against white, so it is only used for bars, rules and
                button fills, never for text on white. That is fine; nothing to change.
              </p>
            )}
            <Field label="Email footer">
              <textarea aria-label="Email footer" rows={4} value={form.footer_text}
                placeholder={"Address, phone, website — up to 6 lines"}
                onChange={(e) => set({ footer_text: e.target.value })} />
            </Field>
            <p className={footerTooLong ? "small" : "small muted"}
              style={footerTooLong ? { color: "var(--bad)" } : undefined}>
              {footerLines} of {FOOTER_MAX_LINES} lines · {form.footer_text.length} of{" "}
              {FOOTER_MAX_CHARS} characters. Shown under every client email, below your own
              sign-off on personal ones.
            </p>
            <div className="row" style={{ gap: "0.5rem" }}>
              <button className="primary" disabled={!colorsValid || blocked || footerTooLong
                || save.isPending} onClick={() => save.mutate(form)}>
                {save.isPending ? "Saving…" : "Save"}
              </button>
              <button className="ghost" disabled={reset.isPending} onClick={() => {
                if (window.confirm("Clear your name, colors, logo, mark and footer, and go back "
                  + "to the defaults?")) reset.mutate();
              }}>Reset to default</button>
            </div>
            {blocked && (
              <p className="small" style={{ color: "var(--bad)" }}>These colors would be hard to read. Adjust the ones marked
                “Too low” to save.</p>
            )}
            {s.branding_updated_at && (
              <p className="small muted">Last saved {when(s.branding_updated_at)}.</p>
            )}
          </Card>

          <Card title="Logo and mark">
            <ImagePicker kind="logo" label="Logo"
              hint="PNG or JPEG, up to 500 KB. Shown up to 260 × 84 px; supply it at about twice that."
              present={s.has_logo} busy={uploadImage.isPending || clearImage.isPending}
              onPick={(file) => uploadImage.mutate({ kind: "logo", file })}
              onClear={() => clearImage.mutate("logo")} />
            <ImagePicker kind="mark" label="Mark (browser tab icon and email sign-off)"
              hint="A square PNG, at least 64 × 64 px; 180 or more looks sharp. Without one, your initials are used."
              present={s.has_mark} busy={uploadImage.isPending || clearImage.isPending}
              onPick={(file) => uploadImage.mutate({ kind: "mark", file })}
              onClear={() => clearImage.mutate("mark")} />
          </Card>
        </div>

        <div style={{ flex: "1 1 22rem", minWidth: 0 }}>
          <Preview form={form} practiceName={s.practice_name} hasLogo={s.has_logo}
            version={version} />
        </div>
      </div>
    </>
  );
}

function ColorField({ label, value, onChange }: {
  label: string; value: string; onChange: (value: string) => void;
}) {
  return (
    <Field label={label}>
      <span className="row" style={{ gap: "0.5rem", alignItems: "center" }}>
        <input type="color" aria-label={`${label} picker`}
          value={HEX.test(value) ? value : "#000000"}
          onChange={(e) => onChange(e.target.value.toUpperCase())}
          style={{ width: "2.75rem", height: "2.25rem", padding: 0 }} />
        <input aria-label={label} value={value} maxLength={7} className="mono"
          style={{ width: "7rem" }}
          onChange={(e) => onChange(e.target.value.trim().toUpperCase())} />
      </span>
    </Field>
  );
}

function ImagePicker({ kind, label, hint, present, busy, onPick, onClear }: {
  kind: "logo" | "mark"; label: string; hint: string; present: boolean; busy: boolean;
  onPick: (file: File) => void; onClear: () => void;
}) {
  return (
    <Field label={label}>
      <span className="row" style={{ gap: "0.5rem", alignItems: "center", flexWrap: "wrap" }}>
        <input type="file" aria-label={`Upload ${kind}`} disabled={busy}
          accept={kind === "logo" ? "image/png,image/jpeg" : "image/png"}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) onPick(file);
            e.target.value = "";
          }} />
        {present && <button className="ghost" disabled={busy} onClick={onClear}>
          Remove</button>}
      </span>
      <span className="small muted">{hint}</span>
    </Field>
  );
}

/** What a client sees, drawn from the unsaved form so changes show at once. */
function Preview({ form, practiceName, hasLogo, version }: {
  form: Form; practiceName: string; hasLogo: boolean; version: number;
}) {
  const primary = HEX.test(form.primary_color) ? form.primary_color : "#1F2933";
  const accent = HEX.test(form.accent_color) ? form.accent_color : "#7B8794";
  const name = form.display_name.trim() || practiceName;
  const logo = hasLogo ? `/api/branding/logo?v=${version}` : "";
  const mark = `/api/branding/mark?v=${version}`;
  return (
    <Card title="Preview">
      <p className="small muted" style={{ marginTop: 0 }}>Browser tab</p>
      <div aria-label="Tab preview" className="row" style={{ gap: "0.5rem", alignItems: "center",
        border: "1px solid var(--line, #E5E7EB)", borderRadius: 8, padding: "0.35rem 0.6rem",
        width: "fit-content" }}>
        <img src={mark} alt="" width={16} height={16} />
        <span className="small">{name}</span>
      </div>

      <p className="small muted">Client portal</p>
      <div aria-label="Portal preview" style={{ display: "flex", border: "1px solid #E5E7EB",
        borderRadius: 8, overflow: "hidden", minHeight: 140 }}>
        <div style={{ background: primary, color: textOn(primary), width: "45%",
          padding: "0.75rem" }}>
          {logo
            ? <img src={logo} alt={name} style={{ maxWidth: "100%", maxHeight: 40,
                background: "#fff", padding: 4, borderRadius: 4 }} />
            : <strong>{name}</strong>}
          <div style={{ marginTop: "0.75rem", borderLeft: `3px solid ${accent}`,
            paddingLeft: "0.5rem" }}>Our work</div>
          <div style={{ marginTop: "0.4rem", paddingLeft: "0.65rem", opacity: 0.8 }}>Tasks</div>
        </div>
        <div style={{ flex: 1, padding: "0.75rem", background: "#F5F7FA" }}>
          <span style={{ display: "inline-block", background: accent, color: textOn(accent),
            borderRadius: 6, padding: "0.3rem 0.7rem", fontSize: "0.85rem" }}>New task</span>
        </div>
      </div>

      <p className="small muted">Email</p>
      <div aria-label="Email preview" style={{ border: "1px solid #E5E7EB", borderRadius: 8,
        overflow: "hidden", background: "#fff" }}>
        <div style={{ padding: "0.75rem" }}>
          {logo ? <img src={logo} alt={name} style={{ maxHeight: 42 }} />
            : <strong style={{ color: primary }}>{name}</strong>}
        </div>
        <div style={{ height: 6, background: primary }} />
        <div style={{ height: 2, background: accent }} />
        <div style={{ padding: "0.75rem" }} className="small">
          Hi Dana, here is what moved this week…
        </div>
        <div aria-label="Footer preview" className="small muted"
          style={{ padding: "0 0.75rem 0.75rem", whiteSpace: "pre-line" }}>
          {form.footer_text.trim() || name}
        </div>
      </div>
    </Card>
  );
}
