import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { ConnectionRead } from "./ConnectionRead";
import { ReadOpenChoice, readOpenValue } from "./ReadOpenChoice";
import { Modal } from "./shell";
import { Banner, Card, Pill } from "./ui";
import { Me, api } from "../lib/api";
import { longDate } from "../lib/money";

/**
 * Google reviews (docs/google_reviews_feed.md): a client company's Google
 * Business Profile location, on the company page, and a KPI's reviews measure.
 * The practice owner starts the connection; whoever manages the client's
 * profile signs in with Google; the account and location are chosen from
 * Google's own lists. Reviews are read nightly and kept; measures are worked
 * out from them.
 */

interface ReviewsConnection {
  connected: boolean; demo: boolean; google_email?: string;
  account?: string; account_label?: string; location?: string; location_title?: string;
  chosen?: boolean; average_rating?: number | null; total_review_count?: number | null;
  not_approved?: boolean; not_approved_text?: string;
  checked_at?: string | null; check_ok?: boolean | null; check_detail?: string;
  last_read_at?: string | null; last_error?: string; stored?: number;
}
interface Review {
  id: string; stars: number | null; comment: string; reviewer: string; created_at: string;
  replied: boolean; reply_at: string | null;
}
interface Choices {
  accounts: { name: string; label: string; type: string }[];
  locations: { name: string; title: string; address: string }[];
  error: string; not_approved: boolean;
}
interface Measure { key: string; label: string; kind: string; star: boolean }
interface ReviewsFeedState {
  kpi: { id: string; name: string; kind: string; per_person: boolean; read_open_default?: boolean };
  connected: boolean; location_title: string; measures: Measure[];
  feed: { measure: string; star: number | null; label: string; text: string;
    last_success_at: string | null; last_error: string; read_open?: boolean } | null;
}

const KEY = (companyId: string) => ["reviews-connection", companyId];

/** "★★★★☆", read aloud as "4 stars". */
export function Stars({ n }: { n: number | null }) {
  if (!n) return <span className="muted">no stars</span>;
  return (
    <span aria-label={`${n} star${n === 1 ? "" : "s"}`} title={`${n} of 5`}
      style={{ color: "var(--orange, #F58220)", letterSpacing: "1px", whiteSpace: "nowrap" }}>
      {"★".repeat(n)}<span style={{ color: "var(--line-strong, #c9ccd1)" }}>{"★".repeat(5 - n)}</span>
    </span>
  );
}

function rating(c: ReviewsConnection) {
  if (c.average_rating == null) return null;
  return `${c.average_rating.toFixed(1)} average from ${c.total_review_count ?? 0} review`
    + `${c.total_review_count === 1 ? "" : "s"}`;
}

/** The connection: sign in, choose the location, Test, Change, Disconnect. */
export function GoogleReviewsCard({ me, companyId }: { me: Me; companyId: string }) {
  const qc = useQueryClient();
  const [params, setParams] = useSearchParams();
  const [said, setSaid] = useState("");
  const [done, setDone] = useState("");
  const [choosing, setChoosing] = useState(false);
  const state = useQuery<ReviewsConnection>({
    queryKey: KEY(companyId),
    queryFn: () => api.get<ReviewsConnection>(`/api/scorecard/reviews/connection/?company=${companyId}`),
  });
  // Back from Google's consent: say what happened, once.
  useEffect(() => {
    const ok = params.get("reviews_connected");
    const bad = params.get("reviews_error");
    if (!ok && !bad) return;
    if (ok) setDone(`Signed in with Google as ${ok}. Now choose the location.`);
    if (bad) setSaid(bad);
    const next = new URLSearchParams(params);
    next.delete("reviews_connected"); next.delete("reviews_error");
    setParams(next, { replace: true });
  }, [params, setParams]);
  const refresh = () => {
    qc.invalidateQueries({ queryKey: KEY(companyId) });
    qc.invalidateQueries({ queryKey: ["reviews-latest", companyId] });
  };
  const fail = (e: Error) => { setDone(""); setSaid(e.message); };
  const start = useMutation({
    mutationFn: () => api.post<{ url: string }>("/api/scorecard/reviews/connection/start/",
      { company: companyId }),
    onSuccess: ({ url }) => { window.location.assign(url); },
    onError: fail,
  });
  const test = useMutation({
    mutationFn: () => api.post<ReviewsConnection>("/api/scorecard/reviews/connection/test/",
      { company: companyId }),
    onSuccess: () => { setSaid(""); refresh(); }, onError: fail,
  });
  const remove = useMutation({
    mutationFn: () => api.del(`/api/scorecard/reviews/connection/?company=${companyId}`),
    onSuccess: () => { setSaid(""); setDone("Disconnected. The KPIs' readings are kept."); refresh(); },
    onError: fail,
  });
  const s = state.data;
  if (!s) return null;
  const owner = me.role === "FF";
  const picking = s.connected && owner && (choosing || !s.chosen);
  return (
    <Card title="Google Business Profile">
      <p className="small muted" style={{ marginTop: 0 }}>
        Feeds this company's Google reviews into its scorecard: new reviews, the average rating, the
        five-star share, unanswered reviews and days to reply. Whoever manages the client's Business
        Profile signs in with Google; the app can only read the reviews, and the sign-in is stored
        encrypted.</p>
      {said && <div role="alert"><Banner kind="bad">{said}</Banner></div>}
      {done && <Banner kind="ok">{done}</Banner>}
      {s.demo && !s.connected && (
        <p className="small">This is the demo. It never signs in to Google.</p>)}
      {s.connected && s.not_approved && (
        <p className="small" role="status" aria-label="Google approval">{s.not_approved_text}</p>)}
      {s.connected && s.chosen && !picking && (
        <div className="track-state">
          <div><strong>{s.location_title || s.location}</strong>{" "}
            <span className="small muted">signed in as {s.google_email}</span></div>
          {rating(s) && <div className="small">{rating(s)}</div>}
          <div className="small">{s.last_read_at
            ? `Last read ${new Date(s.last_read_at).toLocaleString()}.` : "Not read yet."}
            {s.last_error && !s.not_approved && <> The last read said: {s.last_error}</>}</div>
          {s.checked_at && !s.not_approved && (
            <div className="small">{s.check_ok ? `✓ ${s.check_detail}` : `Last test failed: ${s.check_detail}`}</div>)}
          {owner && (
            <div className="row">
              <button className="small" style={{ flex: "0 0 auto" }} disabled={test.isPending}
                onClick={() => test.mutate()}>{test.isPending ? "Testing…" : "Test connection"}</button>
              <button className="ghost small" style={{ flex: "0 0 auto" }}
                onClick={() => { setSaid(""); setDone(""); setChoosing(true); }}>Change</button>
              <button className="ghost small" style={{ flex: "0 0 auto" }} disabled={remove.isPending}
                onClick={() => {
                  if (confirm("Disconnect this location? Its stored reviews go; the KPIs' readings stay.")) {
                    remove.mutate();
                  }
                }}>Disconnect</button>
            </div>
          )}
        </div>
      )}
      {picking && (
        <ChooseLocation companyId={companyId} current={s}
          onSaved={() => { setChoosing(false); setSaid(""); setDone("Location chosen and read."); refresh(); }}
          onCancel={s.chosen ? () => setChoosing(false) : undefined}
          onSignIn={() => start.mutate()} signingIn={start.isPending} />
      )}
      {!s.connected && !s.demo && (owner
        ? <button className="small" disabled={start.isPending} onClick={() => start.mutate()}>
            {start.isPending ? "Opening Google…" : "Sign in with Google"}</button>
        : <p className="small muted">The practice owner connects the company's Business Profile.</p>)}
    </Card>
  );
}

function ChooseLocation({ companyId, current, onSaved, onCancel, onSignIn, signingIn }: {
  companyId: string; current: ReviewsConnection; onSaved: () => void; onCancel?: () => void;
  onSignIn: () => void; signingIn: boolean;
}) {
  const [account, setAccount] = useState(current.account ?? "");
  const [location, setLocation] = useState(current.location ?? "");
  const [error, setError] = useState("");
  const choices = useQuery<Choices>({
    queryKey: ["reviews-choices", companyId, account],
    queryFn: () => api.get<Choices>(`/api/scorecard/reviews/connection/choices/?company=${companyId}`
      + (account ? `&account=${encodeURIComponent(account)}` : "")),
  });
  const accounts = choices.data?.accounts ?? [];
  const locations = choices.data?.locations ?? [];
  useEffect(() => {
    if (!account && accounts.length === 1) setAccount(accounts[0].name);
  }, [account, accounts]);
  const save = useMutation({
    mutationFn: () => api.put("/api/scorecard/reviews/connection/", {
      company: companyId, account, location,
      account_label: accounts.find((a) => a.name === account)?.label ?? "",
      location_title: locations.find((l) => l.name === location)?.title ?? "" }),
    onSuccess: onSaved, onError: (e: Error) => setError(e.message),
  });
  return (
    <div className="track-form">
      <p className="small" style={{ margin: 0 }}>Signed in as {current.google_email}. Choose the
        Business Profile account, then the location whose reviews feed the scorecard.</p>
      {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
      <label htmlFor="reviews-account" className="small">Account</label>
      <select id="reviews-account" value={account} aria-busy={choices.isPending}
        onChange={(e) => { setAccount(e.target.value); setLocation(""); }}>
        <option value="">Choose an account…</option>
        {accounts.map((a) => <option key={a.name} value={a.name}>{a.label}</option>)}
      </select>
      {account && (
        <>
          <label htmlFor="reviews-location" className="small">Location</label>
          <select id="reviews-location" value={location} aria-busy={choices.isPending}
            onChange={(e) => setLocation(e.target.value)}>
            <option value="">Choose a location…</option>
            {locations.map((l) => <option key={l.name} value={l.name}>
              {l.title}{l.address ? ` · ${l.address}` : ""}</option>)}
          </select>
        </>
      )}
      <ConnectionRead source="Google" what={account ? "locations" : "accounts"}
        pending={choices.isPending} meanwhile="" still=""
        error={choices.error ?? (choices.data?.error || null)} />
      <div className="row">
        <button className="primary small" style={{ flex: "0 0 auto" }}
          disabled={!account || !location || save.isPending} onClick={() => save.mutate()}>
          {save.isPending ? "Reading the reviews…" : "Use this location"}</button>
        {onCancel && <button className="ghost small" style={{ flex: "0 0 auto" }} onClick={onCancel}>Cancel</button>}
        <button className="ghost small" style={{ flex: "0 0 auto" }} disabled={signingIn}
          onClick={onSignIn}>Sign in with another Google account</button>
      </div>
    </div>
  );
}

/** The latest reviews, read-only: stars, date, and replied or not. */
export function ReviewsCard({ companyId }: { companyId: string }) {
  const data = useQuery<ReviewsConnection & { reviews: Review[] }>({
    queryKey: ["reviews-latest", companyId],
    queryFn: () => api.get(`/api/scorecard/reviews/latest/?company=${companyId}`),
  });
  const d = data.data;
  if (!d || !d.connected || !d.chosen) return null;
  return (
    <Card title="Google reviews">
      <p className="small muted" style={{ marginTop: 0 }}>
        {d.location_title}{rating(d) ? ` · ${rating(d)}` : ""}. Read once a day; replying is done in
        Google.</p>
      {d.not_approved && <p className="small">{d.not_approved_text}</p>}
      {d.reviews.length === 0 ? <p className="small muted">No reviews stored yet.</p> : (
        <ul aria-label="Latest Google reviews" style={{ listStyle: "none", margin: 0, padding: 0 }}>
          {d.reviews.map((r) => (
            <li key={r.id} style={{ borderTop: "1px solid var(--line)", padding: "var(--s2) 0" }}>
              <div className="row tight" style={{ flexWrap: "wrap", alignItems: "center" }}>
                <Stars n={r.stars} />
                <span className="small">{r.reviewer || "A Google user"}</span>
                <span className="small muted">{longDate(r.created_at.slice(0, 10))}</span>
                {r.replied ? <Pill kind="ok">Replied</Pill> : <Pill kind="warn">Not replied</Pill>}
              </div>
              {r.comment && <p className="small" style={{ margin: "var(--s1) 0 0" }}>{r.comment}</p>}
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

/** A KPI's reviews measure, from a fixed menu. */
export function ReviewsFeedModal({ companyId, kpiId, onClose, onSaved }: {
  companyId: string; kpiId: string; onClose: () => void; onSaved: (text: string) => void;
}) {
  const qc = useQueryClient();
  const state = useQuery<ReviewsFeedState>({
    queryKey: ["reviews-feed", companyId, kpiId],
    queryFn: () => api.get<ReviewsFeedState>(`/api/scorecard/reviews/feed/?company=${companyId}&kpi=${kpiId}`),
  });
  const f = state.data?.feed;
  const [measure, setMeasure] = useState<string | null>(null);
  const [star, setStar] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [readOpen, setReadOpen] = useState<boolean | null>(null);
  const readsOpen = readOpenValue(readOpen, f?.read_open, state.data?.kpi.read_open_default);
  const chosen = measure ?? f?.measure ?? "";
  const def = (state.data?.measures ?? []).find((m) => m.key === chosen);
  const starValue = star ?? f?.star ?? 5;
  const save = useMutation({
    mutationFn: () => api.put<{ run: { ok: boolean; new?: number; error?: string } }>("/api/scorecard/reviews/feed/", {
      company: companyId, kpi: kpiId, measure: chosen, read_open: readsOpen,
      ...(def?.star ? { star: starValue } : {}) }),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["scorecard", companyId] });
      qc.invalidateQueries({ queryKey: ["reviews-feed", companyId, kpiId] });
      const name = state.data?.kpi.name ?? "The KPI";
      onSaved(r.run.ok ? `${name} now reads from Google reviews: ${r.run.new ?? 0} reading`
        + `${r.run.new === 1 ? "" : "s"} for past periods.`
        : `${name}'s Google reviews measure is saved, but: ${r.run.error}`);
    },
    onError: (e: Error) => setError(e.message),
  });
  const stop = useMutation({
    mutationFn: () => api.del(`/api/scorecard/reviews/feed/?company=${companyId}&kpi=${kpiId}`),
    onSuccess: () => onSaved("Entered by hand again. Its readings are kept."),
  });
  const s = state.data;
  const title = s ? `Feed ${s.kpi.name} from Google reviews` : "Google reviews measure";
  return (
    <Modal label={title} title={title} onClose={onClose}>
      {!s ? <p>Loading…</p> : !s.connected ? (
        <p>This company has no Google Business Profile location connected yet. The practice owner
          connects it on the company page, under Google Business Profile.</p>
      ) : (
        <div className="track-feed">
          <p className="small muted" style={{ marginTop: 0 }}>{s.location_title}.
            {f && <> {f.text}.</>}{f?.last_error && <> <strong>Last read:</strong> {f.last_error}</>}</p>
          {error && <div role="alert"><Banner kind="bad">{error}</Banner></div>}
          <label htmlFor="reviews-measure" className="small">Measure</label>
          <select id="reviews-measure" value={chosen}
            onChange={(e) => { setMeasure(e.target.value); setError(""); }}>
            <option value="">Choose a measure…</option>
            {s.measures.map((m) => <option key={m.key} value={m.key}>{m.label}</option>)}
          </select>
          {def?.star && (
            <>
              <label htmlFor="reviews-star" className="small">Stars</label>
              <select id="reviews-star" value={starValue} onChange={(e) => setStar(Number(e.target.value))}>
                {[5, 4, 3, 2, 1].map((n) => <option key={n} value={n}>{n} star{n === 1 ? "" : "s"}</option>)}
              </select>
            </>
          )}
          <p className="small muted">Worked out from the stored reviews for each closed period, once a
            day. A reading typed by hand is never replaced, and none is ever deleted.</p>
          <ReadOpenChoice id="reviews-read-open" checked={readsOpen}
            byDefault={!!s.kpi.read_open_default} onChange={setReadOpen} />
          <div className="row">
            <button className="primary" style={{ flex: "0 0 auto" }} disabled={!chosen || save.isPending}
              onClick={() => save.mutate()}>{save.isPending ? "Working it out…" : "Save the measure"}</button>
            <button className="ghost" style={{ flex: "0 0 auto" }} onClick={onClose}>Cancel</button>
            {f && <button className="ghost" style={{ flex: "0 0 auto" }} onClick={() => stop.mutate()}>Stop the feed</button>}
          </div>
        </div>
      )}
    </Modal>
  );
}
