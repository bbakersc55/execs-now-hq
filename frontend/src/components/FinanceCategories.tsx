import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import {
  CategoryChange, CategoryMoveCount, FinanceCategory, StartingChartPlan, api,
} from "../lib/api";
import { CHART_NOTE, categoryLabel, categoryOptions } from "../lib/finance";
import { longDate } from "../lib/money";
import { Banner, Card, Pill } from "./ui";

/**
 * The chart of categories (P5; P6 M1 §5): two levels, and the tools to change
 * its shape. Combine and split say how many entries would move before they
 * move any, and change no total. "Add the starting chart" only ever adds.
 *
 * The tree is shown to every practice. The tools that reshape it (a
 * sub-category, combine, split, the starting chart) are the Bookkeeping
 * module's, and are not drawn without it.
 */

const TYPES: [FinanceCategory["type"], string, string][] = [
  ["income", "Income", "What the practice earns."],
  ["expense", "Expenses", "What it costs to run."],
  ["owner", "Owner", "Your own money, in or out. Not income and not a cost."],
  ["held", "Held", "Collected for someone else, such as sales tax, until it is paid over."],
];

type Send = (call: { url: string; body: object; method?: "patch" | "delete" },
             after?: () => void) => void;

const span = (count: CategoryMoveCount) => count.entries === 0 ? "No entries"
  : `${count.entries} ${count.entries === 1 ? "entry" : "entries"}`
    + (count.first_on && count.last_on
      ? (count.first_on === count.last_on ? ` dated ${longDate(count.first_on)}`
        : ` from ${longDate(count.first_on)} to ${longDate(count.last_on)}`) : "");

export function FinanceCategories({ categories, bookkeeping, busy, paidInvoicesId, send }: {
  categories: FinanceCategory[]; bookkeeping: boolean; busy: boolean;
  paidInvoicesId: string; send: Send;
}) {
  const [open, setOpen] = useState<{ id: string; tool: "combine" | "split" } | null>(null);
  const top = (type: string) => categories.filter((c) => c.type === type && !c.parent)
    .sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
  const under = (parent: FinanceCategory) => categories.filter((c) => c.parent === parent.id)
    .sort((a, b) => a.position - b.position || a.name.localeCompare(b.name));
  const row = (category: FinanceCategory) => (
    <div key={category.id}>
      <CategoryRow category={category} all={categories} busy={busy} bookkeeping={bookkeeping}
        paidInvoices={paidInvoicesId === category.id}
        hasSubs={under(category).some((c) => !c.archived)}
        onSave={(body) => send({ url: `/api/finance-categories/${category.id}/`, body,
                                 method: "patch" })}
        onRemove={() => send({ url: `/api/finance-categories/${category.id}/`, body: {},
                               method: "delete" })}
        onTool={(tool) => setOpen(open?.id === category.id && open.tool === tool ? null
          : { id: category.id, tool })} />
      {open?.id === category.id && open.tool === "combine" && (
        <Combine category={category} all={categories} onDone={() => setOpen(null)} />)}
      {open?.id === category.id && open.tool === "split" && (
        <Split category={category} all={categories} onDone={() => setOpen(null)} />)}
    </div>
  );
  return (
    <Card title="Categories">
      <p className="small" style={{ marginTop: 0 }}>{CHART_NOTE}</p>
      <p className="small muted">
        A category may have sub-categories, one level down, and an entry may sit on
        either. A category with entries is archived, not removed, and keeps its type. The
        CPA code is yours to fill in if your CPA asks for one; it goes into the export.
      </p>
      {bookkeeping && <StartingChart />}
      {TYPES.map(([type, title, hint]) => (
        <div key={type} style={{ marginBottom: "var(--s4)" }}>
          <h4 style={{ margin: "0 0 2px" }}>{title}</h4>
          <p className="tiny muted" style={{ margin: "0 0 var(--s2)" }}>{hint}</p>
          {top(type).map((parent) => (
            <div key={parent.id} role="group" aria-label={parent.name}>
              {row(parent)}
              <div style={{ marginLeft: "var(--s5)" }}>
                {under(parent).map(row)}
                {bookkeeping && !parent.archived && (
                  <NewCategory label={`New sub-category of ${parent.name}`}
                    placeholder={`A sub-category of ${parent.name}`} busy={busy}
                    onAdd={(name, added) => send(
                      { url: "/api/finance-categories/", body: { name, parent: parent.id } },
                      added)} />)}
              </div>
            </div>
          ))}
          <NewCategory label={`New ${type} category`} placeholder="Another category"
            busy={busy} onAdd={(name, added) => send(
              { url: "/api/finance-categories/", body: { name, type } }, added)} />
        </div>
      ))}
      {bookkeeping && <Changes />}
    </Card>
  );
}

function CategoryRow({ category, all, busy, bookkeeping, paidInvoices, hasSubs, onSave,
                       onRemove, onTool }: {
  category: FinanceCategory; all: FinanceCategory[]; busy: boolean; bookkeeping: boolean;
  paidInvoices: boolean; hasSubs: boolean; onSave: (body: object) => void;
  onRemove: () => void; onTool: (tool: "combine" | "split") => void;
}) {
  const [name, setName] = useState(category.name);
  const [code, setCode] = useState(category.cpa_code);
  useEffect(() => { setName(category.name); setCode(category.cpa_code); },
            [category.name, category.cpa_code]);
  const dirty = name !== category.name || code !== category.cpa_code;
  const went = category.merged_into ? all.find((c) => c.id === category.merged_into) : null;
  // Where it could sit: the top level, or under a live top-level category of
  // its type. One with sub-categories of its own stays at the top.
  const parents = all.filter((c) => c.type === category.type && !c.parent && !c.archived
    && c.id !== category.id);
  const tools = bookkeeping && !category.archived;
  return (
    <div className="row-actions" style={{ marginBottom: "var(--s1)" }}>
      <div className="row-actions-flags">
        <input aria-label={`Name of ${category.name}`} value={name} maxLength={120}
          disabled={busy || category.archived} style={{ minWidth: "16rem" }}
          onChange={(e) => setName(e.target.value)} />
        <input aria-label={`CPA code of ${category.name}`} value={code} maxLength={40}
          placeholder="CPA code" disabled={busy || category.archived} style={{ width: "8rem" }}
          onChange={(e) => setCode(e.target.value)} />
        {dirty && <button className="primary small" disabled={busy || !name.trim()}
          aria-label={`Save ${category.name}`}
          onClick={() => onSave({ name: name.trim(), cpa_code: code.trim() })}>Save</button>}
        {category.archived && <Pill>archived</Pill>}
        {went && <span className="tiny muted">combined into {went.name}</span>}
        {paidInvoices && <Pill kind="ok">paid invoices go here</Pill>}
        {tools && !category.system && !hasSubs && (
          <select aria-label={`Where ${category.name} sits`} disabled={busy}
            value={category.parent ?? ""} style={{ width: "auto" }}
            onChange={(e) => onSave({ parent: e.target.value || null })}>
            <option value="">Top level</option>
            {parents.map((p) => <option key={p.id} value={p.id}>Under {p.name}</option>)}
          </select>)}
      </div>
      <div className="row-actions-cell">
        {tools && !category.system && (
          <button className="ghost small" disabled={busy}
            aria-label={`Combine ${category.name} into another`}
            onClick={() => onTool("combine")}>Combine</button>)}
      </div>
      <div className="row-actions-cell">
        {tools && category.used && (
          <button className="ghost small" disabled={busy} aria-label={`Split ${category.name}`}
            onClick={() => onTool("split")}>Split</button>)}
      </div>
      <div className="row-actions-cell">
        {!(category.system && category.type === "held") && !paidInvoices && (
          category.used === false && !category.system && !hasSubs && !category.archived ? (
            <button className="ghost small" disabled={busy}
              aria-label={`Remove ${category.name}`} onClick={onRemove}>Remove</button>
          ) : (
            <button className="ghost small" disabled={busy}
              aria-label={`${category.archived ? "Restore" : "Archive"} ${category.name}`}
              onClick={() => onSave({ archived: !category.archived })}>
              {category.archived ? "Restore" : "Archive"}</button>
          ))}
      </div>
    </div>
  );
}

function NewCategory({ label, placeholder, busy, onAdd }: {
  label: string; placeholder: string; busy: boolean;
  onAdd: (name: string, added: () => void) => void;
}) {
  const [name, setName] = useState("");
  return (
    <div className="row tight" style={{ margin: "var(--s2) 0" }}>
      <input aria-label={label} value={name} maxLength={120} placeholder={placeholder}
        style={{ width: "16rem" }} onChange={(e) => setName(e.target.value)} />
      <button className="small" disabled={busy || !name.trim()}
        aria-label={`Add: ${label}`}
        onClick={() => onAdd(name.trim(), () => setName(""))}>Add</button>
    </div>
  );
}

const REFRESH = ["finance-categories", "finance-category-changes", "finance-settings",
                 "finance-pnl", "finance-rules", "finance-starting-chart"];

function useChartTool(onDone: () => void) {
  const qc = useQueryClient();
  const [problem, setProblem] = useState("");
  const [count, setCount] = useState<CategoryMoveCount | null>(null);
  const preview = useMutation({
    mutationFn: ({ url, body }: { url: string; body: object }) =>
      api.post<CategoryMoveCount>(url, { ...body, preview: true }),
    onMutate: () => { setProblem(""); setCount(null); },
    onSuccess: setCount, onError: (e: Error) => setProblem(e.message) });
  const apply = useMutation({
    mutationFn: ({ url, body }: { url: string; body: object }) => api.post<unknown>(url, body),
    onSuccess: () => {
      for (const key of REFRESH) qc.invalidateQueries({ queryKey: [key] });
      onDone();
    },
    onError: (e: Error) => setProblem(e.message) });
  return { problem, count, preview, apply, clear: () => { setCount(null); setProblem(""); } };
}

const NO_TOTAL = "No total, balance or net changes. Closed months are included.";

/** A into B: every entry, rule and import line that named A now names B. */
function Combine({ category, all, onDone }: {
  category: FinanceCategory; all: FinanceCategory[]; onDone: () => void;
}) {
  const [into, setInto] = useState("");
  const tool = useChartTool(onDone);
  const url = `/api/finance-categories/${category.id}/merge/`;
  const targets = all.filter((c) => c.type === category.type && !c.archived
    && c.id !== category.id && c.parent !== category.id);
  return (
    <div className="panel" role="group" aria-label={`Combine ${category.name}`}
      style={{ margin: "0 0 var(--s3) var(--s4)" }}>
      <div className="row tight">
        <span className="small">Combine <strong>{category.name}</strong> into</span>
        <select aria-label={`Combine ${category.name} into`} value={into}
          style={{ width: "auto" }}
          onChange={(e) => {
            setInto(e.target.value);
            if (e.target.value) tool.preview.mutate({ url, body: { into: e.target.value } });
            else tool.clear();
          }}>
          <option value="">Choose a category</option>
          {categoryOptions(targets, all).map(([id, label]) => (
            <option key={id} value={id}>{label}</option>))}
        </select>
        <button className="ghost small" onClick={onDone}>Cancel</button>
      </div>
      {tool.problem && <Banner kind="bad">{tool.problem}</Banner>}
      {tool.count && (
        <>
          <p className="small" role="status">
            {span(tool.count)} {tool.count.entries === 1 ? "moves" : "move"} from{" "}
            {tool.count.from} to {tool.count.to}
            {(tool.count.rules ?? 0) > 0 && <>, with {tool.count.rules} import{" "}
              {tool.count.rules === 1 ? "rule" : "rules"}</>}
            {(tool.count.sub_categories ?? 0) > 0 && <>, and its{" "}
              {tool.count.sub_categories} sub-categories go under {tool.count.to}</>}.
            {" "}{NO_TOTAL} {tool.count.from} is then archived. There is no undo; Split is
            the way back.
          </p>
          <button className="primary small" disabled={tool.apply.isPending}
            onClick={() => tool.apply.mutate({ url, body: { into } })}>
            Combine into {tool.count.to}</button>
        </>
      )}
    </div>
  );
}

/** Some of a category's entries to a new category, or to another. */
function Split({ category, all, onDone }: {
  category: FinanceCategory; all: FinanceCategory[]; onDone: () => void;
}) {
  const isSub = !!category.parent;
  const [where, setWhere] = useState<"sub" | "beside" | "existing">(isSub ? "beside" : "sub");
  const [name, setName] = useState("");
  const [to, setTo] = useState("");
  const [contains, setContains] = useState("");
  const tool = useChartTool(onDone);
  const url = `/api/finance-categories/${category.id}/split/`;
  const body = where === "existing" ? { to, contains: contains.trim() }
    : { name: name.trim(), as: where, contains: contains.trim() };
  const ready = contains.trim().length >= 2 && (where === "existing" ? !!to : !!name.trim());
  const targets = all.filter((c) => c.type === category.type && !c.archived
    && c.id !== category.id);
  const changed = () => tool.clear();
  return (
    <div className="panel" role="group" aria-label={`Split ${category.name}`}
      style={{ margin: "0 0 var(--s3) var(--s4)" }}>
      <p className="small" style={{ marginTop: 0 }}>
        Move some of <strong>{category.name}</strong>'s entries somewhere else: the ones
        whose description or payee contains some text.
      </p>
      <div className="row tight">
        <select aria-label="Where the entries go" value={where} style={{ width: "auto" }}
          onChange={(e) => { setWhere(e.target.value as typeof where); changed(); }}>
          {!isSub && <option value="sub">To a new sub-category of {category.name}</option>}
          <option value="beside">To a new category beside {category.name}</option>
          <option value="existing">To a category you already have</option>
        </select>
        {where === "existing" ? (
          <select aria-label="The category they go to" value={to} style={{ width: "auto" }}
            onChange={(e) => { setTo(e.target.value); changed(); }}>
            <option value="">Choose a category</option>
            {categoryOptions(targets, all).map(([id, label]) => (
              <option key={id} value={id}>{label}</option>))}
          </select>
        ) : (
          <input aria-label="Name of the new category" value={name} maxLength={120}
            placeholder="Its name" style={{ width: "14rem" }}
            onChange={(e) => { setName(e.target.value); changed(); }} />
        )}
        <input aria-label="Entries containing" value={contains} maxLength={120}
          placeholder="Entries containing…" style={{ width: "14rem" }}
          onChange={(e) => { setContains(e.target.value); changed(); }} />
        <button className="small" disabled={!ready || tool.preview.isPending}
          onClick={() => tool.preview.mutate({ url, body })}>Count them</button>
        <button className="ghost small" onClick={onDone}>Cancel</button>
      </div>
      {tool.problem && <Banner kind="bad">{tool.problem}</Banner>}
      {tool.count && (
        <>
          <p className="small" role="status">
            {span(tool.count)} {tool.count.entries === 1 ? "moves" : "move"} from{" "}
            {tool.count.from} to {tool.count.to}
            {tool.count.new && <> (new{tool.count.under ? `, under ${tool.count.under}` : ""})</>}
            ; {tool.count.left} {tool.count.left === 1 ? "stays" : "stay"}. {NO_TOTAL}
          </p>
          <button className="primary small"
            disabled={tool.apply.isPending || tool.count.entries === 0}
            onClick={() => tool.apply.mutate({ url, body })}>
            Move {tool.count.entries === 1 ? "it" : "them"} to {tool.count.to}</button>
        </>
      )}
    </div>
  );
}

/** "Add the starting chart": what it would add, shown before it adds it. */
function StartingChart() {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [said, setSaid] = useState("");
  const plan = useQuery<StartingChartPlan>({
    queryKey: ["finance-starting-chart"], enabled: open,
    queryFn: () => api.get<StartingChartPlan>("/api/finance-categories/starting-chart/") });
  const add = useMutation({
    mutationFn: () => api.post<StartingChartPlan>("/api/finance-categories/starting-chart/", {}),
    onSuccess: (done) => {
      setOpen(false);
      setSaid(`Added ${done.added} ${done.added === 1 ? "category" : "categories"}.`);
      for (const key of REFRESH) qc.invalidateQueries({ queryKey: [key] });
    },
    onError: (e: Error) => setSaid(e.message) });
  const tops = (plan.data?.add ?? []).filter((item) => !item.parent);
  const subs = (plan.data?.add ?? []).filter((item) => item.parent);
  return (
    <div style={{ marginBottom: "var(--s4)" }}>
      <div className="row tight">
        <button className="small" onClick={() => { setOpen(!open); setSaid(""); }}>
          Add the starting chart</button>
        <span className="tiny muted">Adds the common categories you do not have. It never
          changes or removes one you do.</span>
      </div>
      {said && <p className="small" role="status">{said}</p>}
      {open && plan.isError && <Banner kind="bad">{(plan.error as Error).message}</Banner>}
      {open && plan.data && (
        <div className="panel" role="group" aria-label="Add the starting chart"
          style={{ marginTop: "var(--s2)" }}>
          {plan.data.add.length === 0 ? (
            <p className="small" style={{ margin: 0 }}>You already have every category in the
              starting chart. There is nothing to add.</p>
          ) : (
            <>
              <p className="small" style={{ marginTop: 0 }}>
                This would add {plan.data.add.length}{" "}
                {plan.data.add.length === 1 ? "category" : "categories"}. Nothing you have is
                renamed, moved, archived or removed, and no entry moves.
              </p>
              {tops.length > 0 && <p className="small"><strong>Categories:</strong>{" "}
                {tops.map((item) => item.name).join(" · ")}</p>}
              {subs.length > 0 && <p className="small"><strong>Sub-categories:</strong>{" "}
                {subs.map((item) => `${item.parent}: ${item.name}`).join(" · ")}</p>}
              <button className="primary small" disabled={add.isPending}
                onClick={() => add.mutate()}>
                Add {plan.data.add.length === 1 ? "it" : `these ${plan.data.add.length}`}</button>
            </>
          )}
          {plan.data.skipped.length > 0 && (
            <p className="tiny muted">Left out: {plan.data.skipped.map(
              (item) => `${item.name} (${item.why})`).join("; ")}.</p>)}
        </div>
      )}
    </div>
  );
}

/** Every combine and split, newest first. */
function Changes() {
  const changes = useQuery<CategoryChange[]>({
    queryKey: ["finance-category-changes"],
    queryFn: () => api.get<CategoryChange[]>("/api/finance-categories/changes/") });
  const rows = changes.data ?? [];
  if (rows.length === 0) return null;
  return (
    <details>
      <summary className="small">Combined and split: {rows.length}</summary>
      <table aria-label="Combined and split">
        <thead><tr><th>When</th><th>What</th><th>Entries</th><th>By</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}>
              <td>{longDate(row.at.slice(0, 10))}</td>
              <td>{row.kind === "merge" ? `${row.from} combined into ${row.to}`
                : `${row.from} split: “${row.contains || "chosen entries"}” to ${row.to}`}</td>
              <td>{row.entries_moved}{row.first_on && row.last_on
                && <span className="muted">, {longDate(row.first_on)} to{" "}
                  {longDate(row.last_on)}</span>}</td>
              <td>{row.by}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </details>
  );
}

export { categoryLabel };
