import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bell } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";

import { Banner, Card } from "./ui";
import { api } from "../lib/api";

/** One thing a person was told (owner, 2026-10-26). The Notices list is the
 *  source of truth: a browser notification is only ever one of these. */
export interface NoticeRow {
  id: string; kind: string; title: string; text: string; url: string;
  created_at: string; read: boolean;
}
interface NoticesData { unread: number; notices: NoticeRow[] }
interface PushState {
  refusal: string; public_key: string; browsers: number;
  kinds: { key: string; label: string; on: boolean }[];
}

/** The Notices list, from the top bar: how many are unread, the latest, and
 *  a click that opens the thing and marks it read. */
export function NoticesBell() {
  const qc = useQueryClient();
  const navigate = useNavigate();
  const [open, setOpen] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const data = useQuery<NoticesData>({
    queryKey: ["notices"], queryFn: () => api.get<NoticesData>("/api/notify/notices/"),
    refetchInterval: 60000,
  });
  const read = useMutation({
    mutationFn: (body: { ids?: string[]; all?: boolean }) => api.post("/api/notify/notices/read/", body),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["notices"] }),
  });
  useEffect(() => {
    if (!open) return;
    const away = (e: PointerEvent) => { if (!wrap.current?.contains(e.target as Node)) setOpen(false); };
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") setOpen(false); };
    document.addEventListener("pointerdown", away);
    document.addEventListener("keydown", esc);
    return () => { document.removeEventListener("pointerdown", away); document.removeEventListener("keydown", esc); };
  }, [open]);
  // Anything but the list's own shape reads as an empty list.
  const d = data.data && Array.isArray(data.data.notices) ? data.data : undefined;
  const unread = d?.unread ?? 0;
  return (
    <div className="notices" ref={wrap}>
      <button type="button" className="icon-button notices-button" aria-haspopup="dialog" aria-expanded={open}
        aria-label={unread ? `Notices, ${unread} unread` : "Notices"} onClick={() => setOpen((o) => !o)}>
        <Bell size={18} strokeWidth={1.75} />
        {unread > 0 && <span className="notices-count" aria-hidden="true">{unread > 99 ? "99+" : unread}</span>}
      </button>
      {open && (
        <div className="notices-panel" role="dialog" aria-label="Notices">
          <div className="notices-head">
            <strong>Notices</strong>
            {unread > 0 && <button className="link small" onClick={() => read.mutate({ all: true })}>Mark all as read</button>}
          </div>
          {(d?.notices ?? []).length === 0 ? <p className="small muted">Nothing yet.</p> : (
            <ul className="notices-list">
              {d!.notices.map((n) => (
                <li key={n.id} className={n.read ? "" : "unread"}>
                  <button type="button" onClick={() => {
                    if (!n.read) read.mutate({ ids: [n.id] });
                    setOpen(false);
                    if (n.url) navigate(n.url);
                  }}>
                    <span className="notices-title">{n.title}</span>
                    <span className="small">{n.text}</span>
                    <span className="tiny muted">{new Date(n.created_at).toLocaleString()}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
    </div>
  );
}

function keyBytes(base64: string): Uint8Array {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  return Uint8Array.from(raw, (c) => c.charCodeAt(0));
}

/** Whether this browser can take Web Push at all. */
export function pushSupported(): boolean {
  return typeof window !== "undefined" && "serviceWorker" in navigator && "PushManager" in window
    && "Notification" in window;
}

/**
 * Profile: "Notify me in the browser". One subscription per browser, turned
 * on and off here; which kinds come is the person's own choice, every one
 * optional. Never on a demo copy, and only where the server has its keys.
 */
export function BrowserNotifications({ editable }: { editable: boolean }) {
  const qc = useQueryClient();
  const state = useQuery<PushState>({
    queryKey: ["push-state"], queryFn: () => api.get<PushState>("/api/notify/push/"),
  });
  const [here, setHere] = useState<"unknown" | "on" | "off">("unknown");
  const [error, setError] = useState("");
  const supported = pushSupported();
  useEffect(() => {
    if (!supported) return;
    navigator.serviceWorker.getRegistration("/").then(async (reg) => {
      const sub = reg ? await reg.pushManager.getSubscription() : null;
      setHere(sub ? "on" : "off");
    }).catch(() => setHere("off"));
  }, [supported]);
  const done = () => qc.invalidateQueries({ queryKey: ["push-state"] });
  const turnOn = useMutation({
    mutationFn: async () => {
      const s = state.data!;
      const permission = await Notification.requestPermission();
      if (permission !== "granted") {
        throw new Error("This browser is set not to show notifications from this site. Allow them in the "
          + "browser's site settings, then try again.");
      }
      const reg = await navigator.serviceWorker.register("/sw.js", { scope: "/" });
      await navigator.serviceWorker.ready;
      const sub = await reg.pushManager.subscribe({
        userVisibleOnly: true, applicationServerKey: keyBytes(s.public_key) as BufferSource });
      const json = sub.toJSON();
      await api.post("/api/notify/push/subscribe/", { endpoint: json.endpoint, keys: json.keys });
    },
    onSuccess: () => { setHere("on"); setError(""); done(); },
    onError: (e: Error) => setError(e.message),
  });
  const turnOff = useMutation({
    mutationFn: async () => {
      const reg = await navigator.serviceWorker.getRegistration("/");
      const sub = reg ? await reg.pushManager.getSubscription() : null;
      if (sub) {
        await api.post("/api/notify/push/unsubscribe/", { endpoint: sub.endpoint });
        await sub.unsubscribe();
      }
    },
    onSuccess: () => { setHere("off"); setError(""); done(); },
    onError: (e: Error) => setError(e.message),
  });
  const kinds = useMutation({
    mutationFn: (next: string[]) => api.put<PushState>("/api/notify/push/", { kinds: next }),
    onSuccess: (s) => qc.setQueryData(["push-state"], s),
    onError: (e: Error) => setError(e.message),
  });
  const s = state.data;
  if (!s || !Array.isArray(s.kinds)) return null;
  const on = s.kinds.filter((k) => k.on).map((k) => k.key);
  return (
    <Card title="Notify me in the browser">
      <p className="small muted" style={{ marginTop: 0 }}>
        What's on your Notices list (the bell at the top) can also pop up in this browser, even when the app
        isn't open. Nothing comes that isn't on the list.</p>
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
      {s.refusal ? <p className="small">{s.refusal}</p>
        : !supported ? <p className="small">This browser can't show notifications from a site.</p>
        : !editable ? <p className="small muted">While acting as someone, their notifications aren't yours to change.</p>
        : (
          <>
            <div className="row tight">
              {here === "on" ? (
                <>
                  <span className="small">On in this browser.</span>
                  <button className="small" disabled={turnOff.isPending} onClick={() => turnOff.mutate()}>
                    Stop in this browser</button>
                </>
              ) : (
                <button className="primary small" disabled={turnOn.isPending || here === "unknown"}
                  onClick={() => turnOn.mutate()}>
                  {turnOn.isPending ? "Asking the browser…" : "Notify me in this browser"}</button>
              )}
            </div>
            {s.browsers > 0 && (
              <fieldset className="push-kinds">
                <legend className="small">Notify me about</legend>
                {s.kinds.map((k) => (
                  <label key={k.key} className="row tight small">
                    <input type="checkbox" checked={k.on} disabled={kinds.isPending}
                      onChange={(e) => kinds.mutate(e.target.checked ? [...on, k.key] : on.filter((x) => x !== k.key))} />
                    {k.label}
                  </label>
                ))}
                <p className="tiny muted" style={{ margin: 0 }}>
                  {s.browsers === 1 ? "On in 1 browser." : `On in ${s.browsers} browsers.`} These choices are for all of them.</p>
              </fieldset>
            )}
          </>
        )}
    </Card>
  );
}
