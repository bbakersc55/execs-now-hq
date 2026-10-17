import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { PriceBox } from "../components/InvoiceLines";
import { SeriesChart } from "../components/SeriesChart";
import { Banner, Card, Empty, Field, Pill } from "../components/ui";
import {
  Asset, Debts, Holding, Holdings, Household, Member, NetWorth, PersonalDebt, Sides, api,
} from "../lib/api";
import { dollars, longDate } from "../lib/money";
import { usePersonalChart } from "../lib/personal";

/**
 * P6 M4 stop 3, decisions 16–19: debts and the payoff plan, retirement and
 * investments, the household, and net worth with a home's equity; and the
 * Overview's two sides set beside each other as numbers.
 *
 * Every figure is the server's arithmetic on what the owner entered or
 * imported. Estimates, not advice: the disclaimer is on every page.
 */

type Said = { kind: string; text: string } | null;

/** Whole dollars when there are no cents. */
function money(cents: number) {
  const text = dollars(cents);
  return text.endsWith(".00") ? text.slice(0, -3) : text;
}

function ordinal(n: number) {
  const teen = n % 100 >= 11 && n % 100 <= 13;
  return `${n}${teen ? "th" : ({ 1: "st", 2: "nd", 3: "rd" } as Record<number, string>)[
    n % 10] ?? "th"}`;
}

function monthYear(iso: string | null) {
  if (!iso) return "—";
  return new Date(`${iso}T12:00:00`).toLocaleDateString(undefined,
                                                        { month: "long", year: "numeric" });
}

function useHousehold() {
  return useQuery<Household>({ queryKey: ["personal-household"],
                               queryFn: () => api.get<Household>("/api/personal/household") });
}

/** The household, or one person (decision 18). */
function WhoseFilter({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const house = useHousehold();
  const members = house.data?.members ?? [];
  if (members.length < 2) return null;
  return (
    <div className="row tight" role="group" aria-label="Whose"
      style={{ marginBottom: "var(--s3)" }}>
      <button className={value === "" ? "small primary" : "small"} aria-pressed={value === ""}
        onClick={() => onChange("")}>The household</button>
      {members.map((m) => (
        <button key={m.id} className={value === m.id ? "small primary" : "small"}
          aria-pressed={value === m.id} onClick={() => onChange(m.id)}>{m.name}</button>
      ))}
    </div>
  );
}

function WhoseSelect({ label, value, onChange, disabled }: {
  label: string; value: string | null; onChange: (v: string | null) => void;
  disabled?: boolean;
}) {
  const members = useHousehold().data?.members ?? [];
  return (
    <select aria-label={label} value={value ?? ""} disabled={disabled}
      style={{ width: "auto" }} onChange={(e) => onChange(e.target.value || null)}>
      <option value="">Joint</option>
      {members.map((m) => <option key={m.id} value={m.id}>{m.name}</option>)}
    </select>
  );
}

// ================================================================== Debts

export function PersonalDebts() {
  const qc = useQueryClient();
  const [whose, setWhose] = useState("");
  // A look at another order or extra: worked out by the server, saved nowhere.
  const [order, setOrder] = useState<"" | "snowball" | "avalanche">("");
  const [extra, setExtra] = useState<number | null>(null);
  const [said, setSaid] = useState<Said>(null);
  const [adding, setAdding] = useState(false);
  const params = new URLSearchParams();
  if (whose) params.set("whose", whose);
  if (order) params.set("order", order);
  if (extra !== null) params.set("extra", String(extra));
  const found = useQuery<Debts>({
    queryKey: ["personal-debts", whose, order, extra],
    queryFn: () => api.get<Debts>(`/api/personal/debts?${params}`) });
  const refresh = () => {
    for (const key of ["personal-debts", "personal-forecast", "personal-budget",
                       "personal-net-worth", "personal-household"]) {
      qc.invalidateQueries({ queryKey: [key] });
    }
  };
  const act = useMutation({
    mutationFn: ({ method, path, body }: { method: "post" | "patch" | "delete"; path: string;
                                           body?: object }) =>
      method === "post" ? api.post(`/api/personal/${path}`, body ?? {})
        : method === "patch" ? api.patch(`/api/personal/${path}`, body)
          : api.del(`/api/personal/${path}`),
    onSuccess: () => { setSaid(null); refresh(); },
    onError: (e: Error) => setSaid({ kind: "bad", text: e.message }) });
  const send = (method: "post" | "patch" | "delete", path: string, body?: object) =>
    act.mutate({ method, path, body });
  const data = found.data;
  if (found.isError) return <Banner kind="bad">{(found.error as Error).message}</Banner>;
  if (!data) return <p>Loading…</p>;
  const looking = (order !== "" && order !== data.saved_order)
    || (extra !== null && extra !== data.saved_extra_cents);
  const ordered = [...data.debts].sort((a, b) => (a.plan_position ?? 99)
    - (b.plan_position ?? 99));
  return (
    <>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <WhoseFilter value={whose} onChange={setWhose} />
      <Card title="Personal: debts"
        actions={!adding && <button className="small" onClick={() => setAdding(true)}>
          Add a debt</button>}>
        <dl className="row" style={{ margin: 0, gap: "var(--s5)" }}
          aria-label="Debts in three figures">
          <div><dt className="small muted">Owed</dt>
            <dd style={{ margin: 0 }}><strong>{money(data.total_cents)}</strong></dd></div>
          <div><dt className="small muted">Minimums a month</dt>
            <dd style={{ margin: 0 }}><strong>{money(data.minimums_cents)}</strong></dd></div>
          <div><dt className="small muted">Debt-free</dt>
            <dd style={{ margin: 0 }}><strong>{data.debt_free_on
              ? monthYear(data.debt_free_on) : "Not at these payments"}</strong></dd></div>
        </dl>
        {adding && <DebtForm busy={act.isPending} onCancel={() => setAdding(false)}
          onSave={(body) => { send("post", "debts", body); setAdding(false); }} />}
      </Card>

      {data.debts.length > 0 && (
        <Card title="The payoff plan">
          <p className="small muted" style={{ marginTop: 0 }}>
            Every minimum is paid. The extra a month, and each paid-off debt's minimum after
            it, go to one debt at a time: <strong>Snowball</strong> takes the smallest
            balance first, <strong>Avalanche</strong> the highest rate. Change either to see
            what it would do; nothing is saved until you save the plan. The extra is an
            envelope in your budget (Debt payments), and the payments are on your forecast.
          </p>
          <div className="row tight" style={{ alignItems: "flex-end" }}>
            <span className="row tight" role="group" aria-label="Which order">
              {(["snowball", "avalanche"] as const).map((o) => (
                <button key={o} aria-pressed={data.order === o}
                  className={data.order === o ? "small primary" : "small"}
                  onClick={() => setOrder(o)}>
                  {o === "snowball" ? "Snowball" : "Avalanche"}</button>
              ))}
            </span>
            <Field label="Extra a month">
              <PriceBox label="Extra a month toward debts" cents={data.extra_cents}
                onChange={(cents) => setExtra(cents)} />
            </Field>
            <button className="small primary" disabled={!looking || act.isPending}
              onClick={() => { send("post", "debts/plan", { order: data.order,
                                                             extra_cents: data.extra_cents });
                               setOrder(""); setExtra(null); }}>Save the plan</button>
            {looking && <button className="ghost small"
              onClick={() => { setOrder(""); setExtra(null); }}>Back to your plan</button>}
          </div>
          {looking && <p className="small"><Pill kind="warn">trying</Pill> Not saved.</p>}
          <ul className="small" aria-label="What the plan does">
            <li>Interest from here on: <strong>{data.interest_cents === null ? "—"
              : money(data.interest_cents)}</strong>, debt-free{" "}
              {monthYear(data.debt_free_on)}.</li>
            <li>{Other(data)}</li>
            {data.extra_cents > 0 && data.extra_saves.interest_cents !== null && (
              <li>The {money(data.extra_cents)} extra saves{" "}
                <strong>{money(data.extra_saves.interest_cents)}</strong> in interest
                {data.extra_saves.months ? ` and ${data.extra_saves.months} months` : ""}{" "}
                against the minimums alone.</li>
            )}
          </ul>
        </Card>
      )}

      {data.debts.length === 0 ? (
        <Card><Empty>No debts yet. Add a mortgage, a car loan or a card above.</Empty></Card>
      ) : ordered.map((debt) => (
        <DebtCard key={debt.id} debt={debt} busy={act.isPending} send={send} />
      ))}
    </>
  );
}

function Other(data: Debts) {
  const name = data.other_order === "avalanche" ? "Avalanche" : "Snowball";
  const cents = data.other.interest_cents;
  if (cents === null) return `${name} cannot be worked out at these payments.`;
  if (cents === 0) return `${name} would cost the same.`;
  const months = data.other.months;
  const when = months ? `, debt-free ${Math.abs(months)} month${Math.abs(months) === 1
    ? "" : "s"} ${months > 0 ? "later" : "sooner"}` : "";
  return `${name} would ${cents > 0 ? "cost" : "save"} ${money(Math.abs(cents))} in interest${
    when}.`;
}

function DebtCard({ debt, busy, send }: {
  debt: PersonalDebt; busy: boolean;
  send: (method: "post" | "patch" | "delete", path: string, body?: object) => void;
}) {
  const [mode, setMode] = useState<"" | "balance" | "edit">("");
  const [cents, setCents] = useState(debt.balance_cents);
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  return (
    <Card title={<>{debt.plan_position && <span className="muted">{debt.plan_position}.{" "}
      </span>}{debt.name}</>}
      actions={<span className="row tight">
        {debt.balance_source !== "import" && (
          <button className="ghost small" onClick={() => setMode("balance")}>
            New balance</button>)}
        <button className="ghost small" onClick={() => setMode("edit")}>Edit</button>
      </span>}>
      <dl className="row small" style={{ margin: 0, gap: "var(--s4)", alignItems: "flex-start" }}
        aria-label={`${debt.name} in figures`}>
        <div><dt className="muted">Owed</dt><dd style={{ margin: 0 }}>
          <strong>{money(debt.balance_cents)}</strong>
          <div className="tiny muted">{debt.balance_source === "import"
            ? "from its statements" : debt.balance_on ? `on ${longDate(debt.balance_on)}`
              : "no balance yet"}</div></dd></div>
        <div><dt className="muted">Kind</dt><dd style={{ margin: 0 }}>{debt.kind_label}
          <div className="tiny muted">{debt.whose_name}</div></dd></div>
        <div><dt className="muted">Rate</dt><dd style={{ margin: 0 }}>
          {debt.rate_percent ? `${Number(debt.rate_percent)}%` : "—"}</dd></div>
        <div><dt className="muted">Minimum</dt><dd style={{ margin: 0 }}>
          {debt.minimum_cents ? money(debt.minimum_cents) : "—"}
          {debt.due_day && <div className="tiny muted">due on the {ordinal(debt.due_day)}
          </div>}</dd></div>
        <div><dt className="muted">Paid off</dt><dd style={{ margin: 0 }}>
          {debt.never ? <Pill kind="bad">not at this payment</Pill>
            : <strong>{monthYear(debt.payoff_on)}</strong>}
          {debt.interest_cents !== null && <div className="tiny muted">
            {money(debt.interest_cents)} interest</div>}</dd></div>
      </dl>
      {debt.never && <p className="small" role="alert">The minimum does not cover the
        interest, so on these figures it is never paid off.</p>}
      <SeriesChart label={`${debt.name}, what is owed`} history={debt.history}
        projection={debt.projected} />
      {mode === "balance" && (
        <div className="row tight" role="group" aria-label={`A new balance for ${debt.name}`}>
          <PriceBox label={`${debt.name}: what is owed`} cents={cents} onChange={setCents} />
          <input type="date" aria-label={`${debt.name}: on`} value={on}
            style={{ width: "auto" }} onChange={(e) => setOn(e.target.value)} />
          <button className="small primary" disabled={busy}
            onClick={() => { send("post", `debts/${debt.id}/balance`,
                                  { balance_cents: cents, on_date: on }); setMode(""); }}>
            Save the balance</button>
          <button className="ghost small" onClick={() => setMode("")}>Cancel</button>
        </div>
      )}
      {mode === "edit" && (
        <DebtForm debt={debt} busy={busy} onCancel={() => setMode("")}
          onSave={(body) => { send("patch", `debts/${debt.id}`, body); setMode(""); }}
          onClose={() => send("delete", `debts/${debt.id}`)} />
      )}
    </Card>
  );
}

const KINDS: [string, string][] = [
  ["mortgage", "Mortgage"], ["auto", "Car loan"], ["card", "Credit card"],
  ["student", "Student loan"], ["personal", "Personal loan"], ["medical", "Medical"],
  ["other", "Other"]];

function DebtForm({ debt, busy, onSave, onCancel, onClose }: {
  debt?: PersonalDebt; busy: boolean; onSave: (body: object) => void; onCancel: () => void;
  onClose?: () => void;
}) {
  const chart = usePersonalChart();
  const [form, setForm] = useState({
    name: debt?.name ?? "", kind: debt?.kind ?? "mortgage", whose: debt?.whose ?? null,
    rate_percent: debt?.rate_percent ?? "", minimum_cents: debt?.minimum_cents ?? 0,
    due_day: debt?.due_day ? String(debt.due_day) : "", balance_cents: 0,
    category: debt?.category?.id ?? "" });
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch });
  const spending = (chart.data?.categories ?? []).filter((c) => c.type === "expense"
    && !c.archived && c.parent);
  const label = debt ? `Editing ${debt.name}` : "The new debt";
  return (
    <div role="group" aria-label={label} style={{ marginTop: "var(--s3)" }}>
      <div className="row">
        <Field label="Name"><input aria-label={`${label}: name`} value={form.name}
          onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field label="Kind">
          <select aria-label={`${label}: kind`} value={form.kind}
            onChange={(e) => set({ kind: e.target.value })}>
            {KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></Field>
        <Field label="Whose"><WhoseSelect label={`${label}: whose`} value={form.whose}
          onChange={(whose) => set({ whose })} /></Field>
        <Field label="Rate, % a year"><input aria-label={`${label}: rate`}
          inputMode="decimal" value={form.rate_percent} style={{ width: "6rem" }}
          onChange={(e) => set({ rate_percent: e.target.value })} /></Field>
        <Field label="Minimum a month"><PriceBox label={`${label}: minimum`}
          cents={form.minimum_cents} onChange={(minimum_cents) => set({ minimum_cents })} />
        </Field>
        <Field label="Due day"><input aria-label={`${label}: due day`} inputMode="numeric"
          value={form.due_day} style={{ width: "4rem" }}
          onChange={(e) => set({ due_day: e.target.value })} /></Field>
        {!debt && <Field label="Owed today"><PriceBox label={`${label}: owed today`}
          cents={form.balance_cents} onChange={(balance_cents) => set({ balance_cents })} />
        </Field>}
        <Field label="Its payments are in">
          <select aria-label={`${label}: payments category`} value={form.category}
            onChange={(e) => set({ category: e.target.value })}>
            <option value="">Not said</option>
            {spending.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select></Field>
      </div>
      <p className="tiny muted" style={{ margin: 0 }}>Naming the category its payments are
        in lets the forecast draw them under the plan instead of as everyday spending.</p>
      <div className="row tight">
        <button className="small primary" disabled={busy || !form.name.trim()}
          onClick={() => onSave({
            name: form.name, kind: form.kind, whose: form.whose,
            rate_percent: form.rate_percent === "" ? null : form.rate_percent,
            minimum_cents: form.minimum_cents || null,
            due_day: form.due_day ? Number(form.due_day) : null,
            category: form.category || null,
            ...(debt ? {} : { balance_cents: form.balance_cents }) })}>
          {debt ? "Save" : "Add it"}</button>
        <button className="ghost small" onClick={onCancel}>Cancel</button>
        {onClose && <button className="ghost small" disabled={busy} onClick={onClose}>
          It is paid off: close it</button>}
      </div>
    </div>
  );
}

// ============================================================= Retirement

export function PersonalRetirement() {
  const qc = useQueryClient();
  const [whose, setWhose] = useState("");
  const [said, setSaid] = useState<Said>(null);
  const [adding, setAdding] = useState(false);
  const [rate, setRate] = useState<string | null>(null);
  const found = useQuery<Holdings>({
    queryKey: ["personal-holdings", whose],
    queryFn: () => api.get<Holdings>(`/api/personal/holdings${whose ? `?whose=${whose}` : ""}`) });
  const act = useMutation({
    mutationFn: ({ method, path, body }: { method: "post" | "patch" | "delete"; path: string;
                                           body?: object }) =>
      method === "post" ? api.post(`/api/personal/${path}`, body ?? {})
        : method === "patch" ? api.patch(`/api/personal/${path}`, body)
          : api.del(`/api/personal/${path}`),
    onSuccess: () => {
      setSaid(null);
      for (const key of ["personal-holdings", "personal-net-worth", "personal-household"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: (e: Error) => setSaid({ kind: "bad", text: e.message }) });
  const send = (method: "post" | "patch" | "delete", path: string, body?: object) =>
    act.mutate({ method, path, body });
  const data = found.data;
  if (found.isError) return <Banner kind="bad">{(found.error as Error).message}</Banner>;
  if (!data) return <p>Loading…</p>;
  return (
    <>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <WhoseFilter value={whose} onChange={setWhose} />
      <Card title="Personal: retirement and investments"
        actions={!adding && <button className="small" onClick={() => setAdding(true)}>
          Add an account</button>}>
        <p className="small" style={{ marginTop: 0 }}>
          <strong>{money(data.total_cents)}</strong> in all. Balances are what you enter,
          monthly or from a statement; nothing is fetched. "On track" grows today's balance
          and what goes in each month at the yearly return you assume:{" "}
          {rate === null ? (
            <><strong>{Number(data.assumed_return_percent)}%</strong>{" "}
              <button className="link" onClick={() => setRate(data.assumed_return_percent)}>
                change it</button></>
          ) : (
            <span className="row tight" style={{ display: "inline-flex" }}>
              <input aria-label="Assumed yearly return, percent" value={rate}
                inputMode="decimal" style={{ width: "5rem" }}
                onChange={(e) => setRate(e.target.value)} />%
              <button className="small" disabled={act.isPending}
                onClick={() => { send("post", "holdings", { assumed_return_percent: rate });
                                 setRate(null); }}>Save</button>
              <button className="ghost small" onClick={() => setRate(null)}>Cancel</button>
            </span>
          )}
        </p>
        <p className="small" role="note"><strong>{data.estimate}</strong></p>
        {adding && <HoldingForm busy={act.isPending} onCancel={() => setAdding(false)}
          onSave={(body) => { send("post", "holdings", body); setAdding(false); }} />}
      </Card>
      {data.holdings.length === 0 ? (
        <Card><Empty>No retirement or investment accounts yet.</Empty></Card>
      ) : data.holdings.map((h) => (
        <HoldingCard key={h.id} holding={h} busy={act.isPending} send={send} />
      ))}
    </>
  );
}

function HoldingCard({ holding, busy, send }: {
  holding: Holding; busy: boolean;
  send: (method: "post" | "patch" | "delete", path: string, body?: object) => void;
}) {
  const [mode, setMode] = useState<"" | "balance" | "edit">("");
  const [cents, setCents] = useState(holding.balance_cents);
  const [on, setOn] = useState(new Date().toISOString().slice(0, 10));
  const s = holding.status;
  const c = holding.contributions;
  return (
    <Card title={holding.name}
      actions={<span className="row tight">
        <button className="ghost small" onClick={() => setMode("balance")}>New balance</button>
        <button className="ghost small" onClick={() => setMode("edit")}>Edit</button>
      </span>}>
      <dl className="row small" style={{ margin: 0, gap: "var(--s4)", alignItems: "flex-start" }}
        aria-label={`${holding.name} in figures`}>
        <div><dt className="muted">Balance</dt><dd style={{ margin: 0 }}>
          <strong>{money(holding.balance_cents)}</strong>
          <div className="tiny muted">{holding.balance_on
            ? `on ${longDate(holding.balance_on)}` : "none yet"}</div></dd></div>
        <div><dt className="muted">{holding.kind_label}</dt><dd style={{ margin: 0 }}>
          {holding.whose_name}</dd></div>
        <div><dt className="muted">Goes in a month</dt><dd style={{ margin: 0 }}>
          {money(c.monthly_cents)}
          <div className="tiny muted">{c.recognized
            ? `seen in your lines (“${holding.contribution_text}”)`
            : holding.typed_monthly_cents ? "as you typed it" : "none seen or typed"}
          </div></dd></div>
        <div><dt className="muted">Target</dt><dd style={{ margin: 0 }}>
          {holding.target_cents ? <>{money(holding.target_cents)} by {holding.target_year}</>
            : "None"}</dd></div>
        {s && (
          <div><dt className="muted">On this course</dt><dd style={{ margin: 0 }}>
            {s.on_track ? <Pill kind="good">on track</Pill> : <Pill kind="warn">behind</Pill>}
            <div className="tiny muted">{money(s.projected_cents)} by then
              {!s.on_track && <>; {money(s.needed_monthly_cents)} a month would reach it</>}
            </div></dd></div>
        )}
      </dl>
      <SeriesChart label={`${holding.name}, its balance`} history={holding.history}
        projection={s?.projection.slice(1) ?? []} target={holding.target_cents}
        targetLabel={holding.target_year ? `target by ${holding.target_year}` : undefined} />
      {mode === "balance" && (
        <div className="row tight" role="group" aria-label={`A new balance for ${holding.name}`}>
          <PriceBox label={`${holding.name}: balance`} cents={cents} onChange={setCents} />
          <input type="date" aria-label={`${holding.name}: on`} value={on}
            style={{ width: "auto" }} onChange={(e) => setOn(e.target.value)} />
          <button className="small primary" disabled={busy}
            onClick={() => { send("post", `holdings/${holding.id}/balance`,
                                  { balance_cents: cents, on_date: on }); setMode(""); }}>
            Save the balance</button>
          <button className="ghost small" onClick={() => setMode("")}>Cancel</button>
        </div>
      )}
      {mode === "edit" && (
        <HoldingForm holding={holding} busy={busy} onCancel={() => setMode("")}
          onSave={(body) => { send("patch", `holdings/${holding.id}`, body); setMode(""); }}
          onClose={() => send("delete", `holdings/${holding.id}`)} />
      )}
    </Card>
  );
}

function HoldingForm({ holding, busy, onSave, onCancel, onClose }: {
  holding?: Holding; busy: boolean; onSave: (body: object) => void; onCancel: () => void;
  onClose?: () => void;
}) {
  const [form, setForm] = useState({
    name: holding?.name ?? "", kind: holding?.kind ?? "retirement",
    whose: holding?.whose ?? null, target_cents: holding?.target_cents ?? 0,
    target_year: holding?.target_year ? String(holding.target_year) : "",
    contribution_text: holding?.contribution_text ?? "",
    monthly_cents: holding?.typed_monthly_cents ?? 0, balance_cents: 0 });
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch });
  const label = holding ? `Editing ${holding.name}` : "The new account";
  return (
    <div role="group" aria-label={label} style={{ marginTop: "var(--s3)" }}>
      <div className="row">
        <Field label="Name"><input aria-label={`${label}: name`} value={form.name}
          onChange={(e) => set({ name: e.target.value })} /></Field>
        <Field label="Kind">
          <select aria-label={`${label}: kind`} value={form.kind}
            onChange={(e) => set({ kind: e.target.value as Holding["kind"] })}>
            <option value="retirement">Retirement</option>
            <option value="investment">Investment</option>
          </select></Field>
        <Field label="Whose"><WhoseSelect label={`${label}: whose`} value={form.whose}
          onChange={(whose) => set({ whose })} /></Field>
        {!holding && <Field label="Balance today"><PriceBox label={`${label}: balance`}
          cents={form.balance_cents} onChange={(balance_cents) => set({ balance_cents })} />
        </Field>}
        <Field label="Target"><PriceBox label={`${label}: target`} cents={form.target_cents}
          onChange={(target_cents) => set({ target_cents })} /></Field>
        <Field label="By the year"><input aria-label={`${label}: target year`}
          inputMode="numeric" value={form.target_year} style={{ width: "5rem" }}
          onChange={(e) => set({ target_year: e.target.value })} /></Field>
        <Field label="Lines that say (contributions)"><input
          aria-label={`${label}: contribution text`} value={form.contribution_text}
          placeholder="VANGUARD ROTH" onChange={(e) => set({ contribution_text: e.target.value })} />
        </Field>
        <Field label="Or a month, typed"><PriceBox label={`${label}: monthly`}
          cents={form.monthly_cents} onChange={(monthly_cents) => set({ monthly_cents })} />
        </Field>
      </div>
      <p className="tiny muted" style={{ margin: 0 }}>Contributions are recognized from
        lines out of your accounts that say the text you give. Where none shows them (paid
        from the practice, or from pay), type what goes in a month.</p>
      <div className="row tight">
        <button className="small primary" disabled={busy || !form.name.trim()}
          onClick={() => onSave({
            name: form.name, kind: form.kind, whose: form.whose,
            target_cents: form.target_cents || null,
            target_year: form.target_year ? Number(form.target_year) : null,
            contribution_text: form.contribution_text, monthly_cents: form.monthly_cents || null,
            ...(holding ? {} : { balance_cents: form.balance_cents }) })}>
          {holding ? "Save" : "Add it"}</button>
        <button className="ghost small" onClick={onCancel}>Cancel</button>
        {onClose && <button className="ghost small" disabled={busy} onClick={onClose}>
          Close this account</button>}
      </div>
    </div>
  );
}

// ============================================================== Household

const RELATIONS: [Member["relation"], string][] = [
  ["spouse", "Spouse"], ["partner", "Partner"], ["other", "Someone else"]];

export function PersonalHousehold() {
  const qc = useQueryClient();
  const house = useHousehold();
  const [said, setSaid] = useState<Said>(null);
  const [adding, setAdding] = useState(false);
  const act = useMutation({
    mutationFn: ({ method, path, body }: { method: "post" | "patch" | "delete"; path: string;
                                           body?: object }) =>
      method === "post" ? api.post<Household>(`/api/personal/${path}`, body ?? {})
        : method === "patch" ? api.patch<Household>(`/api/personal/${path}`, body)
          : api.del<Household>(`/api/personal/${path}`),
    onSuccess: (now) => {
      setSaid(null); qc.setQueryData(["personal-household"], now);
      for (const key of ["personal-debts", "personal-holdings", "personal-net-worth"]) {
        qc.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: (e: Error) => setSaid({ kind: "bad", text: e.message }) });
  const send = (method: "post" | "patch" | "delete", path: string, body?: object) =>
    act.mutate({ method, path, body });
  const data = house.data;
  if (house.isError) return <Banner kind="bad">{(house.error as Error).message}</Banner>;
  if (!data) return <p>Loading…</p>;
  const groups: [string, string][] = [["income", "Income"], ["account", "Accounts"],
    ["debt", "Debts"], ["holding", "Retirement and investments"], ["asset", "Things owned"]];
  return (
    <>
      {said && <Banner kind={said.kind}>{said.text}</Banner>}
      <Card title="Personal: your household"
        actions={!adding && <button className="small" onClick={() => setAdding(true)}>
          Add someone</button>}>
        <p className="small muted" style={{ marginTop: 0 }}>
          The people your money is shared with. A person here is a label, not a sign-in:
          nobody but you sees any of this. Debts, Retirement and the Overview can show the
          household or one person.
        </p>
        <table aria-label="The household">
          <tbody>
            {data.members.map((m) => (
              <MemberRow key={m.id} member={m} busy={act.isPending} send={send} />
            ))}
          </tbody>
        </table>
        {adding && <MemberForm busy={act.isPending} onCancel={() => setAdding(false)}
          onSave={(body) => { send("post", "household", body); setAdding(false); }} />}
      </Card>
      {data.income.length > 0 && (
        <Card title="What each brings in">
          <table aria-label="Income by person">
            <thead><tr><th>Income</th><th>Whose</th>
              <th className="money">A month, typically</th></tr></thead>
            <tbody>
              {data.income.map((row) => (
                <tr key={row.category}><td>{row.category}</td><td>{row.whose_name}</td>
                  <td className="money">{money(row.monthly_cents)}</td></tr>
              ))}
            </tbody>
          </table>
          <p className="tiny muted">The middle of your last months, from your lines.</p>
        </Card>
      )}
      <Card title="Whose is what">
        <p className="small muted" style={{ marginTop: 0 }}>Joint is everyone's; one
          person's view shows only what is theirs.</p>
        {groups.map(([what, title]) => {
          const rows = data.things.filter((t) => t.what === what);
          if (rows.length === 0) return null;
          return (
            <section key={what} aria-label={title}>
              <h4 style={{ marginBottom: "var(--s1)" }}>{title}</h4>
              <table>
                <tbody>
                  {rows.map((t) => (
                    <tr key={`${t.thing}:${t.id}`}>
                      <td>{t.name} <span className="small muted">{t.label}</span></td>
                      <td className="money">
                        <WhoseSelect label={`Whose is ${t.name}`} value={t.whose}
                          disabled={act.isPending}
                          onChange={(whose) => send("post", "household/whose",
                                                    { thing: t.thing, id: t.id, whose })} />
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          );
        })}
      </Card>
    </>
  );
}

function MemberRow({ member, busy, send }: {
  member: Member; busy: boolean;
  send: (method: "post" | "patch" | "delete", path: string, body?: object) => void;
}) {
  const [editing, setEditing] = useState(false);
  if (editing) {
    return (
      <tr><td colSpan={3}>
        <MemberForm member={member} busy={busy} onCancel={() => setEditing(false)}
          onSave={(body) => { send("patch", `members/${member.id}`, body); setEditing(false); }} />
      </td></tr>
    );
  }
  return (
    <tr>
      <td><strong>{member.name}</strong> <span className="small muted">
        {member.is_you ? "You" : member.relation_label}</span></td>
      <td className="small">{member.expected_withholding_cents !== null
        && <>Expected withholding this year: {money(member.expected_withholding_cents)}{" "}
          <span className="muted">(kept for the tax estimate)</span></>}</td>
      <td className="money">
        <button className="ghost small" onClick={() => setEditing(true)}
          aria-label={`Edit ${member.name}`}>Edit</button>
        {!member.is_you && <button className="ghost small" disabled={busy}
          aria-label={`Take ${member.name} out of the household`}
          onClick={() => send("delete", `members/${member.id}`)}>Take out</button>}
      </td>
    </tr>
  );
}

function MemberForm({ member, busy, onSave, onCancel }: {
  member?: Member; busy: boolean; onSave: (body: object) => void; onCancel: () => void;
}) {
  const [name, setName] = useState(member?.name ?? "");
  const [relation, setRelation] = useState<Member["relation"]>(member?.relation ?? "spouse");
  const [withholding, setWithholding] = useState(member?.expected_withholding_cents ?? 0);
  const label = member ? `Editing ${member.name}` : "Someone new";
  return (
    <div role="group" aria-label={label} className="row tight"
      style={{ alignItems: "flex-end", marginTop: "var(--s2)" }}>
      <Field label="Name"><input aria-label={`${label}: name`} value={name}
        onChange={(e) => setName(e.target.value)} /></Field>
      {!member?.is_you && (
        <Field label="Who they are">
          <select aria-label={`${label}: relation`} value={relation}
            onChange={(e) => setRelation(e.target.value as Member["relation"])}>
            {RELATIONS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select></Field>
      )}
      {!member?.is_you && (
        <Field label="Expected W-2 withholding this year">
          <PriceBox label={`${label}: withholding`} cents={withholding}
            onChange={setWithholding} /></Field>
      )}
      <button className="small primary" disabled={busy || !name.trim()}
        onClick={() => onSave({ name, ...(member?.is_you ? {} : {
          relation, expected_withholding_cents: withholding || null }) })}>
        {member ? "Save" : "Add"}</button>
      <button className="ghost small" onClick={onCancel}>Cancel</button>
    </div>
  );
}

// ============================================== the Overview: two sides, net worth

/** Decision 15: both sides' cash at the end of 90 days, as numbers side by
 *  side. Never one chart. */
export function SidesCard() {
  const found = useQuery<Sides>({ queryKey: ["personal-sides"],
                                  queryFn: () => api.get<Sides>("/api/personal/sides") });
  const data = found.data;
  if (!data) return null;
  const side = (title: string, s: Sides["personal"] | null, to: string, none: string) => (
    <div style={{ minWidth: "14rem" }}>
      <h4 style={{ margin: "0 0 var(--s1)" }}>{title}</h4>
      {s === null ? <p className="small muted" style={{ margin: 0 }}>{none}</p> : (
        <>
          <p style={{ margin: 0 }}><strong>{money(s.end_cents)}</strong>{" "}
            <span className="small muted">in {data.days} days</span></p>
          <p className="small muted" style={{ margin: 0 }}>{money(s.cash_today_cents)} today;
            lowest {money(s.low_cents)}, the week of {longDate(s.low_start)}</p>
          <Link className="small" to={to}>Open the forecast</Link>
        </>
      )}
    </div>
  );
  return (
    <Card title="Cash in 90 days, both sides">
      <div className="row" style={{ gap: "var(--s6)", alignItems: "flex-start" }}>
        {side("Personal", data.personal, "/finance/personal/forecast", "")}
        {side("Business", data.business, "/finance/forecast",
              "The practice's cash forecast is not switched on.")}
      </div>
      <p className="tiny muted" style={{ marginBottom: 0 }}>Two forecasts, each on its own
        accounts, set side by side. Neither is added to the other.</p>
    </Card>
  );
}

export function NetWorthCard() {
  const qc = useQueryClient();
  const [whose, setWhose] = useState("");
  const [adding, setAdding] = useState(false);
  const [error, setError] = useState("");
  const found = useQuery<NetWorth>({
    queryKey: ["personal-net-worth", whose],
    queryFn: () => api.get<NetWorth>(`/api/personal/net-worth${whose ? `?whose=${whose}`
      : ""}`) });
  const act = useMutation({
    mutationFn: ({ method, path, body }: { method: "post" | "patch" | "delete"; path: string;
                                           body?: object }) =>
      method === "post" ? api.post(`/api/personal/${path}`, body ?? {})
        : method === "patch" ? api.patch(`/api/personal/${path}`, body)
          : api.del(`/api/personal/${path}`),
    onSuccess: () => { setError(""); qc.invalidateQueries({ queryKey: ["personal-net-worth"] });
                       qc.invalidateQueries({ queryKey: ["personal-household"] }); },
    onError: (e: Error) => setError(e.message) });
  const send = (method: "post" | "patch" | "delete", path: string, body?: object) =>
    act.mutate({ method, path, body });
  const data = found.data;
  if (!data) return null;
  return (
    <Card title="Net worth"
      actions={!adding && <button className="small" onClick={() => setAdding(true)}>
        Add a home or vehicle</button>}>
      <WhoseFilter value={whose} onChange={setWhose} />
      {error && <Banner kind="bad">{error}</Banner>}
      <dl className="row" style={{ margin: 0, gap: "var(--s5)" }}
        aria-label="Net worth in three figures">
        <div><dt className="small muted">Net worth today</dt>
          <dd style={{ margin: 0 }}><strong>{money(data.total_cents)}</strong>
            {data.change_cents !== null && data.since && (
              <div className="tiny muted">{data.change_cents >= 0 ? "up " : "down "}
                {money(Math.abs(data.change_cents))} since {longDate(data.since)}</div>
            )}</dd></div>
        <div><dt className="small muted">What you have</dt>
          <dd style={{ margin: 0 }}>{money(data.assets_cents)}</dd></div>
        <div><dt className="small muted">What you owe</dt>
          <dd style={{ margin: 0 }}>{money(data.debts_cents)}</dd></div>
      </dl>
      <SeriesChart label="Net worth" history={data.series} height={160} zero={false} />
      {data.equity.length > 0 && (
        <ul className="small" aria-label="Equity">
          {data.equity.map((e) => (
            <li key={e.id}><strong>{e.name}</strong>: worth {money(e.value_cents)} (
              {longDate(e.value_on)}), {money(e.owed_cents)} owed on {e.debt},{" "}
              <strong>{money(e.equity_cents)} equity</strong></li>
          ))}
        </ul>
      )}
      <details>
        <summary className="small">What it is made of</summary>
        <table aria-label="What net worth is made of">
          <tbody>
            {data.assets.map((a) => (
              <tr key={`a:${a.name}`}><td>{a.name}</td><td className="money">
                {money(a.cents)}</td></tr>
            ))}
            {data.debts.map((d) => (
              <tr key={`d:${d.name}`}><td>{d.name}</td><td className="money">
                −{money(d.cents)}</td></tr>
            ))}
          </tbody>
        </table>
        <p className="tiny muted">Your accounts from their lines; retirement, investments,
          debts and things owned on their newest figure. No values are fetched. A Mixed card
          is your practice's account, so it is not counted here.</p>
      </details>
      {data.things.length > 0 && (
        <table aria-label="Things owned">
          <tbody>
            {data.things.map((t) => <ThingRow key={t.id} thing={t} busy={act.isPending}
              send={send} />)}
          </tbody>
        </table>
      )}
      {adding && <ThingForm busy={act.isPending} onCancel={() => setAdding(false)}
        onSave={(body) => { send("post", "net-worth", body); setAdding(false); }} />}
    </Card>
  );
}

function ThingRow({ thing, busy, send }: {
  thing: Asset; busy: boolean;
  send: (method: "post" | "patch" | "delete", path: string, body?: object) => void;
}) {
  const [valuing, setValuing] = useState(false);
  const [cents, setCents] = useState(thing.value_cents);
  return (
    <tr>
      <td>{thing.name} <span className="small muted">{thing.kind_label}
        {thing.debt ? `, against ${thing.debt.name}` : ""}</span></td>
      <td className="money">{money(thing.value_cents)}
        {thing.value_on && <div className="tiny muted">{longDate(thing.value_on)}</div>}</td>
      <td className="money">
        {valuing ? (
          <span className="row tight" style={{ justifyContent: "flex-end" }}>
            <PriceBox label={`${thing.name}: what it is worth today`} cents={cents}
              onChange={setCents} />
            <button className="small" disabled={busy}
              onClick={() => { send("patch", `assets/${thing.id}`, { value_cents: cents });
                               setValuing(false); }}>Save</button>
            <button className="ghost small" onClick={() => setValuing(false)}>Cancel</button>
          </span>
        ) : (
          <>
            <button className="ghost small" aria-label={`A new value for ${thing.name}`}
              onClick={() => setValuing(true)}>New value</button>
            <button className="ghost small" disabled={busy}
              aria-label={`${thing.name} is sold or gone`}
              onClick={() => send("delete", `assets/${thing.id}`)}>Sold or gone</button>
          </>
        )}
      </td>
    </tr>
  );
}

function ThingForm({ busy, onSave, onCancel }: {
  busy: boolean; onSave: (body: object) => void; onCancel: () => void;
}) {
  const debts = useQuery<Debts>({ queryKey: ["personal-debts", "", "", null],
                                  queryFn: () => api.get<Debts>("/api/personal/debts?") });
  const [form, setForm] = useState({ name: "", kind: "home", whose: null as string | null,
                                     debt: "", value_cents: 0,
                                     value_on: new Date().toISOString().slice(0, 10) });
  const set = (patch: Partial<typeof form>) => setForm({ ...form, ...patch });
  const label = "Something owned";
  return (
    <div role="group" aria-label={label} style={{ marginTop: "var(--s3)" }}>
      <div className="row">
        <Field label="What it is"><input aria-label={`${label}: name`} value={form.name}
          placeholder="The house on Aspen Court" onChange={(e) => set({ name: e.target.value })} />
        </Field>
        <Field label="Kind">
          <select aria-label={`${label}: kind`} value={form.kind}
            onChange={(e) => set({ kind: e.target.value })}>
            <option value="home">Home</option><option value="vehicle">Vehicle</option>
            <option value="other">Something else</option>
          </select></Field>
        <Field label="Whose"><WhoseSelect label={`${label}: whose`} value={form.whose}
          onChange={(whose) => set({ whose })} /></Field>
        <Field label="Worth"><PriceBox label={`${label}: worth`} cents={form.value_cents}
          onChange={(value_cents) => set({ value_cents })} /></Field>
        <Field label="As of"><input type="date" aria-label={`${label}: as of`}
          value={form.value_on} onChange={(e) => set({ value_on: e.target.value })} /></Field>
        <Field label="The loan against it">
          <select aria-label={`${label}: loan`} value={form.debt}
            onChange={(e) => set({ debt: e.target.value })}>
            <option value="">None</option>
            {(debts.data?.debts ?? []).map((d) => <option key={d.id} value={d.id}>{d.name}
              </option>)}
          </select></Field>
      </div>
      <div className="row tight">
        <button className="small primary" disabled={busy || !form.name.trim()
          || form.value_cents <= 0}
          onClick={() => onSave({ ...form, debt: form.debt || null })}>Add it</button>
        <button className="ghost small" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
