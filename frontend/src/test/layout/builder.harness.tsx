import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import ReactDOM from "react-dom/client";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import { BuilderSection, BuilderTemplate, StrategyQuestion } from "../../lib/api";
import { TemplateBuilder } from "../../screens/TemplateBuilder";
import "../../theme.css";
import { aMe } from "../fixtures";

/**
 * The builder with every kind of section, in a real browser, for
 * `builderLayout.test.ts`: jsdom lays nothing out, so where a column of
 * buttons sits can only be measured here. It talks to no server (`fetch` is
 * answered below), and writes what it measured into `#layout` as JSON.
 */

const ID = "aaaaaaaa-1111-4222-8333-444444444444";

function q(key: string, prompt: string, more: Partial<StrategyQuestion> = {}): StrategyQuestion {
  return { key, prompt, ask_when: "live", must_ask: false, area: "",
           response_schema: "free_text", is_fractional_observation: false,
           has_fractional_note: false, is_financial: false, position: 0, label: "",
           pdf_chip: false, ...more };
}

function part(kind: BuilderSection["kind"], code: string, title: string,
              questions: StrategyQuestion[], more: Partial<BuilderSection> = {}): BuilderSection {
  return { code, kind, title, time_budget_minutes: kind === "precall" ? null : 5,
           included: true, optional: kind === "values", response_schema: null, most: 12,
           fixed_count: kind === "paths", questions, ...more };
}

// Every kind, with a different number of flags in each: none (ratings), one
// (diagnostic, mirror, values), two (scope), a long one (pre-call), no move
// or Remove at all (paths), and a section of the practice's own.
const TEMPLATE: BuilderTemplate = {
  id: ID, name: "Strategy session", format: "v3", is_default: false, archived_at: null,
  ready: true, missing: [], merge_fields: ["Company", "Practice", "Visionary"],
  settings: { advisor_role: "fractional operations executive",
              rating_scale: "1 means not true today, 10 means completely true",
              path_a_title: "Continue to run it yourself",
              path_a_points: ["Use the map", "Your team carries it"],
              path_b_title: "Work with {Practice}",
              path_b_points: ["We work the map with you", "Alongside your team"],
              diagnostic_size: 3 },
  example: { start_from: "operations_example", version: 2,
             unchanged_settings: ["advisor_role"] },
  sections: [
    part("precall", "snapshot", "Before the call", [
      q("p1", "Revenue — last year / this year", { ask_when: "precall", label: "Revenue",
                                                   pdf_chip: true, from_example: true }),
      q("p2", "Software stack — and what lives in someone's head instead of a system",
        { ask_when: "precall" }),
    ], { most: 20 }),
    part("ratings", "six_key_components", "Ratings", [
      q("r1", "Vision — Our 3-year picture is clear and shared.",
        { response_schema: "rating_1_10", label: "Vision" }),
      q("r2", "People — We have the right people in the right seats.",
        { response_schema: "rating_1_10", label: "People" }),
    ], { most: 8 }),
    part("diagnostic", "diagnostic", "Diagnostic", [
      q("d1", "Where do decisions stall because they need {Visionary}?",
        { response_schema: "diagnostic_triple", must_ask: true }),
    ], { most: 8 }),
    part("custom", "custom_ab12cd34", "Leadership bench", [
      q("c1", "Who runs the day to day?"),
      q("c2", "Org chart shared", { response_schema: "agreed_note" }),
    ], { optional: true, custom: true, show_in_pdf: true,
         schemas: ["free_text", "diagnostic_triple", "agreed_note"] }),
    part("mirror", "mirror", "The mirror and where they want to go", [
      q("m1", "3-year picture — revenue, locations, roles"),
      q("m2", "Do they describe the destination the same way?",
        { is_fractional_observation: true }),
    ], { most: 5 }),
    part("map", "strategy_map", "Strategy Map", [], { most: 0 }),
    part("values", "what_they_value", "What they value", [
      q("v1", "Value 1 — in their words, and why it matters to them",
        { response_schema: "value_pair" }),
    ], { most: 5 }),
    part("paths", "two_paths", "Two paths", [
      q("a", "Path A — They run it", { response_schema: "path_reaction" }),
      q("b", "Path B — Run it together", { response_schema: "path_reaction" }),
    ], { most: 2 }),
    part("scope", "scope_agreement", "Scope", [
      q("s1", "Start date", { response_schema: "agreed_note" }),
      q("s2", "Investment range discussed", { response_schema: "agreed_note",
                                              is_financial: true, must_ask: true }),
    ]),
    part("custom", "custom_99887766", "Removed section", [],
         { included: false, optional: true, custom: true, show_in_pdf: false,
           schemas: ["free_text"] }),
  ],
};

window.fetch = async () => new Response(JSON.stringify(TEMPLATE), {
  status: 200, headers: { "Content-Type": "application/json" } });

const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
ReactDOM.createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={client}>
    <MemoryRouter initialEntries={[`/strategy/templates/${ID}/build`]}>
      <Routes>
        <Route path="/strategy/templates/:id/build" element={<TemplateBuilder me={aMe()} />} />
      </Routes>
    </MemoryRouter>
  </QueryClientProvider>,
);

const box = (el: Element | null | undefined) => {
  if (!el) return null;
  const r = el.getBoundingClientRect();
  const round = (n: number) => Math.round(n * 100) / 100;
  return { x: round(r.left), y: round(r.top), w: round(r.width), h: round(r.height) };
};
const named = (el: Element) => el.getAttribute("aria-label") || el.textContent?.trim() || "";

function measure() {
  const rows = Array.from(document.querySelectorAll(".row-actions")).map((row) => {
    const cell = (name: string) => row.querySelector(`[data-cell="${name}"]`);
    return {
      section: row.closest("section.card")?.querySelector("h3")?.textContent ?? "",
      flags: cell("flags")!.querySelectorAll("label").length,
      up: box(cell("up")), down: box(cell("down")), remove: box(cell("remove")),
      upButton: box(cell("up")!.querySelector("button")),
      downButton: box(cell("down")!.querySelector("button")),
      removeButton: box(cell("remove")!.querySelector("button")),
    };
  });
  const controls = Array.from(document.querySelectorAll(
    "button:not(.link):not(.icon-button), a.btn, select, "
    + "input:not([type='checkbox']):not([type='radio'])"))
    .map((el) => ({ what: `${el.tagName.toLowerCase()}: ${named(el)}`, ...box(el)! }));
  const name = document.querySelector("[aria-label='Template name']");
  const beside = Array.from(name?.closest(".row")?.parentElement?.querySelectorAll(
    ":scope > button, :scope > a.btn") ?? []);
  return {
    sections: Array.from(document.querySelectorAll("section.card h3"))
      .map((h) => h.textContent ?? ""),
    rows, controls,
    nameRow: { name: box(name),
               beside: beside.map((el) => ({ what: named(el), ...box(el)! })) },
  };
}

// Once the builder is on the page and the fonts have settled.
const started = Date.now();
const timer = window.setInterval(async () => {
  const ready = document.querySelectorAll(".row-actions").length > 0;
  if (!ready && Date.now() - started < 8000) return;
  window.clearInterval(timer);
  await document.fonts.ready;
  document.getElementById("layout")!.textContent = JSON.stringify(
    ready ? measure() : { error: "the builder did not render" });
}, 50);
