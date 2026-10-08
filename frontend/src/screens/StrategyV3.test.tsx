import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  BuilderSection, BuilderTemplate, StrategyQuestion, StrategySessionRow,
  StrategyTemplateRow,
} from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { SessionDetail } from "./SessionDetail";
import { SessionTemplate } from "./SessionTemplate";
import { Sessions } from "./Sessions";
import { TemplateBuilder } from "./TemplateBuilder";

/**
 * P3 phase 5 — the screens for builder (v3) templates and sessions. The
 * classic and focused screens are covered, unchanged, by `Strategy.test.tsx`.
 */

const TEMPLATE_ID = "aaaaaaaa-1111-4222-8333-444444444444";
const SESSION_ID = "11111111-2222-4333-8444-555555555555";
const ROOT = `/api/strategy-template-builder/${TEMPLATE_ID}/`;

function q(key: string, prompt: string, more: Partial<StrategyQuestion> = {}): StrategyQuestion {
  return { key, prompt, ask_when: "live", must_ask: false, area: "",
           response_schema: "free_text", is_fractional_observation: false,
           has_fractional_note: false, is_financial: false, position: 0, label: "",
           pdf_chip: false, ...more };
}

function part(kind: BuilderSection["kind"], code: string, title: string,
              questions: StrategyQuestion[] = [],
              more: Partial<BuilderSection> = {}): BuilderSection {
  return { code, kind, title, time_budget_minutes: kind === "precall" ? null : 5,
           included: true, optional: kind === "values", response_schema: null,
           most: kind === "map" ? 0 : 8, fixed_count: kind === "paths", questions, ...more };
}

function aBuilder(overrides: Partial<BuilderTemplate> = {}): BuilderTemplate {
  return {
    id: TEMPLATE_ID, name: "Our session", format: "v3", is_default: false,
    archived_at: null, ready: false,
    missing: ["Ratings needs at least 2 rated items (it has 1)."],
    merge_fields: ["Company", "Practice", "Visionary"],
    settings: { advisor_role: "advisor",
                rating_scale: "1 means not true today, 10 means completely true",
                path_a_title: "Continue to run it yourself",
                path_a_points: ["Use the map", "Your team carries it"],
                path_b_title: "Work with {Practice}",
                path_b_points: ["We work the map with you", "Alongside your team"],
                diagnostic_size: 3 },
    sections: [
      part("precall", "snapshot", "Before the call", [
        q("p1", "What does {Company} sell?", { ask_when: "precall", label: "Sells" }),
        q("p2", "How many people work there?", { ask_when: "precall" }),
      ], { most: 20 }),
      part("ratings", "six_key_components", "Ratings", [
        q("r1", "Plan — Our plan is written down.", { response_schema: "rating_1_10",
                                                       label: "Plan" }),
      ]),
      part("diagnostic", "diagnostic", "Diagnostic"),
      part("mirror", "mirror", "The mirror and where they want to go"),
      part("map", "strategy_map", "Strategy Map"),
      part("values", "what_they_value", "What they value"),
      part("paths", "two_paths", "Two paths", [
        q("a", "Path A — Continue to run it yourselves", { response_schema: "path_reaction" }),
        q("b", "Path B — Work with us", { response_schema: "path_reaction" }),
      ]),
      part("scope", "scope_agreement", "Scope", [
        q("s1", "Investment discussed", { response_schema: "agreed_note",
                                          is_financial: true }),
      ]),
    ],
    ...overrides,
  };
}

function showBuilder(template = aBuilder(), me = aMe(), extra: Record<string, unknown> = {},
                     route = `/strategy/templates/${TEMPLATE_ID}/build`) {
  const fetchMock = mockApi({ ...extra, [`GET ${ROOT}`]: template });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<TemplateBuilder me={me} />, { path: "/strategy/templates/:id/build", route });
  return fetchMock;
}

const sent = (fetchMock: ReturnType<typeof mockApi>, suffix: string) =>
  fetchMock.calls.filter((c) => c.method !== "GET" && c.url.endsWith(suffix)).map((c) => c.body);

beforeEach(() => { vi.unstubAllGlobals(); });

// ================================================================ the builder

describe("the template builder", () => {
  it("lays out the eight parts in order and says what is missing", async () => {
    showBuilder();
    expect(await screen.findByRole("heading", { name: "Our session" })).toBeInTheDocument();
    const titles = ["Before the call", "Ratings", "Diagnostic",
                    "The mirror and where they want to go", "Strategy Map",
                    "What they value", "Two paths", "Scope"];
    const found = Array.from(document.querySelectorAll(".card-title, .card h2, .card h3"))
      .map((h) => h.textContent ?? "");
    expect(found.filter((t) => titles.includes(t))).toEqual(titles);
    expect(screen.getByText("Not ready to run")).toBeInTheDocument();
    expect(within(screen.getByRole("list", { name: "What this template still needs" }))
      .getByText("Ratings needs at least 2 rated items (it has 1).")).toBeInTheDocument();
    expect(screen.getByText(/never changes a session already created/)).toBeInTheDocument();
    // Not ready: it cannot be made the default.
    expect(screen.getByRole("button", { name: "Make this the practice default" })).toBeDisabled();
  });

  it("adds a rated item with its label, and keeps a refused wording in the box", async () => {
    let refuse = true;
    const fetchMock = showBuilder(aBuilder(), aMe(), {
      [`POST ${ROOT}questions/`]: () => refuse
        ? { status: 400, body: { detail: "This one is rated 1–10. “What” asks for an "
            + "explanation." } }
        : { status: 201, body: aBuilder() },
    });
    const wording = await screen.findByLabelText("Wording of the new one in Ratings");
    const add = screen.getByRole("button", { name: "Add a rated item" });
    await userEvent.type(wording, "What is your team like?");
    expect(add).toBeDisabled();                       // a rated item needs its label
    await userEvent.type(screen.getByLabelText("Label of the new one in Ratings"), "Team");
    await userEvent.click(add);
    expect(await screen.findByText(/asks for an explanation/)).toBeInTheDocument();
    expect(wording).toHaveValue("What is your team like?");
    refuse = false;
    await userEvent.clear(wording);
    await userEvent.type(wording, "Team — The seats are filled.");
    await userEvent.click(add);
    await waitFor(() => expect(wording).toHaveValue(""));
    expect(sent(fetchMock, "questions/").at(-1)).toEqual({
      section: "six_key_components", prompt: "Team — The seats are filled.", label: "Team" });
  });

  it("saves a reworded question only when Save is pressed", async () => {
    const fetchMock = showBuilder(aBuilder(), aMe(), { [`POST ${ROOT}question/`]: aBuilder() });
    const box = await screen.findByLabelText("Wording of: What does {Company} sell?");
    expect(screen.queryByRole("button", { name: "Save: What does {Company} sell?" }))
      .not.toBeInTheDocument();
    await userEvent.clear(box);
    await userEvent.type(box, "What does {{Company} clean?");
    expect(sent(fetchMock, "question/")).toEqual([]);
    await userEvent.click(screen.getByRole("button", { name: "Save: What does {Company} sell?" }));
    expect(sent(fetchMock, "question/")).toEqual([
      { key: "p1", prompt: "What does {Company} clean?" }]);
  });

  it("marks a labelled pre-call answer for the PDF header, and not an unlabelled one",
    async () => {
      const fetchMock = showBuilder(aBuilder(), aMe(), { [`POST ${ROOT}question/`]: aBuilder() });
      const labelled = await screen.findByLabelText("Show in the PDF header: Sells");
      expect(screen.getByLabelText("Show in the PDF header: How many people work there?"))
        .toBeDisabled();
      await userEvent.click(labelled);
      expect(sent(fetchMock, "question/")).toEqual([{ key: "p1", pdf_chip: true }]);
    });

  it("never offers to add or remove a path, and offers nothing to add to the map",
    async () => {
      showBuilder();
      await screen.findByLabelText("Wording of: Path B — Work with us");
      expect(screen.queryByRole("button", { name: /^Remove: Path/ })).not.toBeInTheDocument();
      expect(screen.queryByLabelText("Wording of the new one in Two paths"))
        .not.toBeInTheDocument();
      expect(screen.queryByLabelText("Wording of the new one in Strategy Map"))
        .not.toBeInTheDocument();
      expect(screen.getByLabelText("Money: Investment discussed")).toBeChecked();
    });

  it("saves the practice's own settings: diagnostic size, scale, paths and Claude's wording",
    async () => {
      const fetchMock = showBuilder(aBuilder(), aMe(), { [`POST ${ROOT}settings/`]: aBuilder() });
      const size = await screen.findByLabelText("Diagnostic questions per session");
      await userEvent.clear(size);
      await userEvent.type(size, "6");
      await userEvent.click(screen.getByRole("button",
        { name: "Save Diagnostic questions per session" }));
      const line = screen.getByLabelText("Path B line 2 on the document");
      await userEvent.clear(line);
      await userEvent.type(line, "On site every week");
      await userEvent.click(screen.getByRole("button",
        { name: "Save Path B line 2 on the document" }));
      const role = screen.getByLabelText("How Claude describes the practice");
      await userEvent.clear(role);
      await userEvent.type(role, "business consultant");
      await userEvent.click(screen.getByRole("button",
        { name: "Save How Claude describes the practice" }));
      expect(sent(fetchMock, "settings/")).toEqual([
        { settings: { diagnostic_size: 6 } },
        { settings: { path_b_points: ["We work the map with you", "On site every week"] } },
        { settings: { advisor_role: "business consultant" } },
      ]);
    });

  it("takes What they value out, and puts it back", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = showBuilder(aBuilder(), aMe(), { [`POST ${ROOT}include/`]: aBuilder() });
    await userEvent.click(await screen.findByRole("button",
      { name: "Take “What they value” out of this template" }));
    expect(sent(fetchMock, "include/")).toEqual([{ kind: "values", included: false }]);
    // Only that part offers it.
    expect(screen.getAllByRole("button", { name: /out of this template/ })).toHaveLength(1);
  });

  it("shows a part that is out, with the way back", async () => {
    const off = aBuilder();
    off.sections = off.sections.map((s) => s.kind === "values" ? { ...s, included: false } : s);
    const fetchMock = showBuilder(off, aMe(), { [`POST ${ROOT}include/`]: aBuilder() });
    expect(await screen.findByText("not in this template")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Put “What they value” back in" }));
    expect(sent(fetchMock, "include/")).toEqual([{ kind: "values", included: true }]);
  });

  it("is read-only for an associate and an assistant", async () => {
    for (const role of ["CF", "VA"] as const) {
      const { unmount } = (() => { showBuilder(aBuilder(), aMe({ role })); return { unmount: () =>
        document.body.replaceChildren() }; })();
      expect(await screen.findByText(/the practice owner's to edit/)).toBeInTheDocument();
      expect(screen.getByLabelText("Wording of: What does {Company} sell?")).toBeDisabled();
      expect(screen.queryByRole("button", { name: "Add a rated item" })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /^Remove:/ })).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: /out of this template/ }))
        .not.toBeInTheDocument();
      unmount();
    }
  });

  it("fills suggested wordings from a session's prep, unsaved", async () => {
    const fetchMock = showBuilder(aBuilder(), aMe(), {
      [`GET /api/strategy-sessions/${SESSION_ID}/`]: {
        id: SESSION_ID, prep: { rewordings: [
          { key: "p1", current: "What does Acme sell?", suggested: "What does Acme clean?",
            why: "Their site" }] } },
      [`POST ${ROOT}question/`]: aBuilder(),
    }, `/strategy/templates/${TEMPLATE_ID}/build?session=${SESSION_ID}&prefill=p1`);
    expect(await screen.findByText(/Filled in 1 question from your prep/)).toBeInTheDocument();
    expect(screen.getByLabelText("Wording of: What does {Company} sell?"))
      .toHaveValue("What does Acme clean?");
    expect(screen.getByText("Not saved yet.")).toBeInTheDocument();
    expect(sent(fetchMock, "question/")).toEqual([]);
    expect(screen.getByRole("link", { name: "Back to the session" }))
      .toHaveAttribute("href", `/strategy/${SESSION_ID}`);
  });

  it("says so when the template is not a builder template", async () => {
    vi.stubGlobal("fetch", mockApi({ [`GET ${ROOT}`]: () => ({ status: 409, body: {
      detail: "“Operations — focused” is not a builder template. It is edited in the "
        + "template editor, as before." } }) }));
    renderRoute(<TemplateBuilder me={aMe()} />, { path: "/strategy/templates/:id/build",
      route: `/strategy/templates/${TEMPLATE_ID}/build` });
    expect(await screen.findByText(/edited in the template editor/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Back to the templates" }))
      .toHaveAttribute("href", "/strategy/template");
  });
});

describe("sections of your own in the builder", () => {
  const custom = (more: Partial<BuilderSection> = {}) => part(
    "custom", "custom_ab12cd34", "Leadership bench", [
      q("c1", "Who runs the day to day?"),
      q("c2", "Where does hiring stall?", { response_schema: "diagnostic_triple" }),
    ], { most: 12, optional: true, custom: true, show_in_pdf: false,
         schemas: ["free_text", "diagnostic_triple", "agreed_note"], ...more });
  const withCustom = (more: Partial<BuilderSection> = {}) => {
    const base = aBuilder();
    return aBuilder({ sections: [...base.sections.slice(0, 3), custom(more),
                                 ...base.sections.slice(3)] });
  };

  it("adds a section with its title, minutes and place on the call", async () => {
    const fetchMock = showBuilder(aBuilder(), aMe(), {
      [`POST ${ROOT}sections/`]: () => ({ status: 201, body: aBuilder() }) });
    const add = await screen.findByRole("button", { name: "Add a section" });
    expect(add).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Title of the new section"), "Leadership bench");
    await userEvent.type(screen.getByLabelText("Minutes for the new section"), "10");
    // Anywhere among the parts on the call, the first place included.
    const where = screen.getByLabelText("Where the new section goes");
    expect(within(where).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Last on the call", "After “Before the call”", "After “Ratings”", "After “Diagnostic”",
      "After “The mirror and where they want to go”", "After “Strategy Map”",
      "After “What they value”", "After “Two paths”", "After “Scope”"]);
    await userEvent.selectOptions(where, "diagnostic");
    await userEvent.click(add);
    await waitFor(() => expect(sent(fetchMock, "sections/")).toEqual([
      { title: "Leadership bench", time_budget_minutes: 10, after: "diagnostic" }]));
  });

  it("moves any section on the call, and never the part before it", async () => {
    const fetchMock = showBuilder(withCustom(), aMe(), {
      [`POST ${ROOT}move-section/`]: () => ({ status: 200, body: withCustom() }) });
    await screen.findByText("Our session");
    expect(screen.queryByLabelText("Move section up: Before the call")).not.toBeInTheDocument();
    // First and last on the call have nowhere further to go.
    expect(screen.getByLabelText("Move section up: Ratings")).toBeDisabled();
    expect(screen.getByLabelText("Move section down: Scope")).toBeDisabled();
    for (const title of ["Strategy Map", "Two paths", "Scope", "Leadership bench"]) {
      expect(screen.getByLabelText(`Move section up: ${title}`)).toBeEnabled();
    }
    await userEvent.click(screen.getByLabelText("Move section up: Leadership bench"));
    await userEvent.click(screen.getByLabelText("Move section down: Strategy Map"));
    await waitFor(() => expect(sent(fetchMock, "move-section/")).toEqual([
      { code: "custom_ab12cd34", by: -1 }, { code: "strategy_map", by: 1 }]));
  });

  it("says what a section of your own is, and gives each new question a kind of answer",
    async () => {
      const fetchMock = showBuilder(withCustom(), aMe(), {
        [`POST ${ROOT}questions/`]: () => ({ status: 201, body: withCustom() }) });
      expect(await screen.findByText(/Claude does not read it/)).toBeInTheDocument();
      expect(screen.getAllByText("Said / cause / tried").length).toBeGreaterThan(1);
      const kind = screen.getByLabelText("Kind of answer for the new one in Leadership bench");
      expect(within(kind).getAllByRole("option").map((o) => o.textContent)).toEqual([
        "A written answer", "Said / cause / tried", "Agreed, with a note"]);
      await userEvent.type(
        screen.getByLabelText("Wording of the new one in Leadership bench"), "Org chart shared");
      await userEvent.selectOptions(kind, "agreed_note");
      const card = kind.closest(".card") as HTMLElement;
      await userEvent.click(within(card).getByRole("button", { name: "Add a question" }));
      await waitFor(() => expect(sent(fetchMock, "questions/")).toEqual([
        { section: "custom_ab12cd34", prompt: "Org chart shared",
          response_schema: "agreed_note" }]));
      // One of the eight parts offers no such choice.
      expect(screen.queryByLabelText("Kind of answer for the new one in Diagnostic"))
        .not.toBeInTheDocument();
    });

  it("prints a section of your own only when ticked, and offers that on no other part",
    async () => {
      const fetchMock = showBuilder(withCustom(), aMe(), {
        [`POST ${ROOT}section/`]: () => ({ status: 200, body: withCustom() }) });
      const print = await screen.findByLabelText(
        "Print this section on the document: Leadership bench");
      expect(print).not.toBeChecked();
      expect(screen.getAllByLabelText(/^Print this section on the document/)).toHaveLength(1);
      await userEvent.click(print);
      await waitFor(() => expect(sent(fetchMock, "section/")).toEqual([
        { code: "custom_ab12cd34", show_in_pdf: true }]));
    });

  it("takes a section of your own out by its code, and puts it back", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    const fetchMock = showBuilder(withCustom(), aMe(), {
      [`POST ${ROOT}include/`]: () => ({ status: 200, body: withCustom() }) });
    await userEvent.click(await screen.findByRole("button", {
      name: "Take “Leadership bench” out of this template" }));
    await waitFor(() => expect(sent(fetchMock, "include/")).toEqual([
      { code: "custom_ab12cd34", included: false }]));
    vi.unstubAllGlobals();
    const out = showBuilder(withCustom({ included: false, questions: [] }), aMe(), {
      [`POST ${ROOT}include/`]: () => ({ status: 200, body: withCustom() }) });
    await userEvent.click((await screen.findAllByRole("button", {
      name: "Put “Leadership bench” back in" })).at(-1)!);
    await waitFor(() => expect(sent(out, "include/")).toEqual([
      { code: "custom_ab12cd34", included: true }]));
    // What they value still goes by its kind, as before.
  });

  it("stops offering a new section at eight of your own", async () => {
    const base = aBuilder();
    showBuilder(aBuilder({ sections: [...base.sections, ...Array.from({ length: 8 }, (_, n) =>
      custom({ code: `custom_0000000${n}`, title: `Section ${n}` }))] }));
    expect(await screen.findByText(/8 sections of your own at most/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Add a section" })).not.toBeInTheDocument();
  });

  it("gives an associate or an assistant none of the section controls", async () => {
    showBuilder(withCustom(), aMe({ role: "CF" }));
    await screen.findByText("Our session");
    expect(screen.queryByRole("button", { name: "Add a section" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/^Move section/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Print this section on the document: Leadership bench"))
      .toBeDisabled();
  });
});

describe("paste several", () => {
  const PASTE = `${ROOT}paste/`;
  const line = (prompt: string, ok = true, why = "", label = "") => ({ prompt, label, ok, why });
  const result = (lines: ReturnType<typeof line>[], more: Record<string, unknown> = {}) => ({
    section: "snapshot", lines, adding: lines.filter((l) => l.ok).length, added: [],
    stale: false, template: aBuilder(), ...more });

  it("is on the six cards that hold questions, and not on the paths or the map", async () => {
    showBuilder();
    await screen.findByText("Our session");
    expect(screen.getAllByRole("button", { name: /^Paste several into / })
      .map((b) => b.getAttribute("aria-label"))).toEqual([
      "Paste several into Before the call", "Paste several into Ratings",
      "Paste several into Diagnostic",
      "Paste several into The mirror and where they want to go",
      "Paste several into What they value", "Paste several into Scope"]);
  });

  it("shows the list back, and adds nothing until it is confirmed", async () => {
    const fetchMock = showBuilder(aBuilder(), aMe(), {
      [`POST ${PASTE}`]: (body: { confirmed?: string[] }) => body.confirmed
        ? { status: 201, body: result([line("What do you sell?"), line("How many sites?")],
                                      { added: ["k1", "k2"] }) }
        : { status: 200, body: result([line("What do you sell?"), line("How many sites?")]) } });
    await userEvent.click(
      await screen.findByRole("button", { name: "Paste several into Before the call" }));
    const show = screen.getByRole("button", { name: "Show the list" });
    expect(show).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Lines to paste into Before the call"),
      "1. What do you sell?{Enter}2. How many sites?");
    await userEvent.click(show);
    const list = await screen.findByLabelText("What would be added to Before the call");
    expect(within(list).getAllByRole("listitem")).toHaveLength(2);
    expect(screen.getByText(/All 2 questions can be added/)).toBeInTheDocument();
    expect(screen.getByText(/Nothing has been added yet/)).toBeInTheDocument();
    // Shown, not sent for adding.
    expect(sent(fetchMock, "paste/")).toEqual([
      { section: "snapshot", text: "1. What do you sell?\n2. How many sites?" }]);
    await userEvent.click(screen.getByRole("button", { name: "Add 2 questions" }));
    await waitFor(() => expect(sent(fetchMock, "paste/")).toHaveLength(2));
    expect(sent(fetchMock, "paste/")[1]).toEqual({
      section: "snapshot", text: "1. What do you sell?\n2. How many sites?",
      confirmed: ["What do you sell?", "How many sites?"] });
    // Done: the box is closed again.
    await waitFor(() => expect(
      screen.queryByLabelText("What would be added to Before the call")).not.toBeInTheDocument());
  });

  it("marks a refused line with why, and offers to add only the others", async () => {
    const fetchMock = showBuilder(aBuilder(), aMe(), {
      [`POST ${PASTE}`]: () => ({ status: 200, body: result([
        line("Plan — Our plan is written down.", true, "", "Plan"),
        line("People — Who runs each division?", false,
             "This one is rated 1–10. “Who” asks for an explanation.", "People"),
        line("We review the numbers weekly.", false, "A rated item needs a short label."),
      ], { section: "six_key_components" }) }) });
    await userEvent.click(
      await screen.findByRole("button", { name: "Paste several into Ratings" }));
    expect(screen.getByText(/Start each line with its label/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Lines to paste into Ratings"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Show the list" }));
    const items = within(await screen.findByLabelText("What would be added to Ratings"))
      .getAllByRole("listitem");
    expect(items[0]).toHaveTextContent("will be added");
    expect(items[0]).toHaveTextContent("Plan · Plan — Our plan is written down.");
    expect(items[1]).toHaveTextContent("left out");
    expect(items[1]).toHaveTextContent("asks for an explanation");
    expect(items[2]).toHaveTextContent("A rated item needs a short label.");
    expect(screen.getByText(/1 rated item of 3 can be added/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Add 1 rated item" }));
    await waitFor(() => expect(sent(fetchMock, "paste/")[1]).toMatchObject({
      confirmed: ["Plan — Our plan is written down."] }));
  });

  it("offers nothing to add when every line is refused, and lets the list be changed",
    async () => {
      showBuilder(aBuilder(), aMe(), {
        [`POST ${PASTE}`]: () => ({ status: 200, body: result([
          line("Start date", false, "This is already in this part, word for word.")]) }) });
      await userEvent.click(
        await screen.findByRole("button", { name: "Paste several into Scope" }));
      await userEvent.type(screen.getByLabelText("Lines to paste into Scope"), "Start date");
      await userEvent.click(screen.getByRole("button", { name: "Show the list" }));
      expect(await screen.findByRole("button", { name: "Add 0 items" })).toBeDisabled();
      await userEvent.click(screen.getByRole("button", { name: "Change the list" }));
      // What was typed is still there to fix.
      expect(screen.getByLabelText("Lines to paste into Scope")).toHaveValue("Start date");
    });

  it("says so when the list cannot be read at all", async () => {
    showBuilder(aBuilder(), aMe(), {
      [`POST ${PASTE}`]: () => ({ status: 400,
                                  body: { detail: "That is 61 lines. Paste 50 at most at a time." } }) });
    await userEvent.click(
      await screen.findByRole("button", { name: "Paste several into Diagnostic" }));
    await userEvent.type(screen.getByLabelText("Lines to paste into Diagnostic"), "x");
    await userEvent.click(screen.getByRole("button", { name: "Show the list" }));
    expect(await screen.findByText(/Paste 50 at most/)).toBeInTheDocument();
  });

  it("shows the list again, with nothing added, when the template changed meanwhile",
    async () => {
      showBuilder(aBuilder(), aMe(), {
        [`POST ${PASTE}`]: (body: { confirmed?: string[] }) => body.confirmed
          ? { status: 409, body: result([line("One"), line("Two", false, "holds 5 at most")],
                                        { stale: true }) }
          : { status: 200, body: result([line("One"), line("Two")]) } });
      await userEvent.click(
        await screen.findByRole("button", { name: "Paste several into What they value" }));
      await userEvent.type(screen.getByLabelText("Lines to paste into What they value"), "x");
      await userEvent.click(screen.getByRole("button", { name: "Show the list" }));
      await userEvent.click(await screen.findByRole("button", { name: "Add 2 values" }));
      expect(await screen.findByText(/nothing was added/)).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Add 1 value" })).toBeInTheDocument();
      expect(screen.getByText("holds 5 at most")).toBeInTheDocument();
    });

  it("cancels without sending anything", async () => {
    const fetchMock = showBuilder();
    await userEvent.click(
      await screen.findByRole("button", { name: "Paste several into Scope" }));
    await userEvent.type(screen.getByLabelText("Lines to paste into Scope"), "Who signs");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByLabelText("Lines to paste into Scope")).not.toBeInTheDocument();
    expect(sent(fetchMock, "paste/")).toEqual([]);
  });

  it("is not offered to an associate or an assistant, or on a full part", async () => {
    showBuilder(aBuilder(), aMe({ role: "VA" }));
    await screen.findByText("Our session");
    expect(screen.queryByRole("button", { name: /^Paste several/ })).not.toBeInTheDocument();
    vi.unstubAllGlobals();
    const full = aBuilder();
    full.sections[0].most = 2;
    showBuilder(full);
    await screen.findAllByText("Our session");
    expect(screen.queryAllByRole("button", { name: "Paste several into Before the call" }))
      .toHaveLength(0);
  });
});

describe("a template made from the Operations example", () => {
  const fromExample = (overrides: Partial<BuilderTemplate> = {}) => {
    const base = aBuilder({ ready: true, missing: [] });
    return aBuilder({
      ready: true, missing: [],
      settings: { ...base.settings, advisor_role: "fractional operations executive" },
      example: { start_from: "operations_example", version: 2,
                 unchanged_settings: ["advisor_role"] },
      sections: base.sections.map((section) => ({
        ...section,
        questions: section.questions.map((question) => ({
          ...question, from_example: question.key !== "p2",
          is_fractional_observation: question.key === "b" })) })),
      ...overrides });
  };
  beforeEach(() => { window.localStorage.clear(); });

  it("says where it came from until dismissed, and stays dismissed", async () => {
    showBuilder(fromExample());
    expect(await screen.findByText(/Made from the Operations example/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    expect(screen.queryByText(/Made from the Operations example/)).not.toBeInTheDocument();
    vi.unstubAllGlobals();
    showBuilder(fromExample());
    await screen.findAllByText("from the example");
    expect(screen.queryByText(/Made from the Operations example/)).not.toBeInTheDocument();
  });

  it("tags each line still worded as the example has it, and not a reworded one",
    async () => {
      showBuilder(fromExample());
      await screen.findByText(/Made from the Operations example/);
      // Five of the six questions, and Wording for Claude.
      expect(screen.getAllByText("from the example")).toHaveLength(6);
      const reworded = screen.getByLabelText("Wording of: How many people work there?");
      expect(within(reworded.closest(".field") as HTMLElement)
        .queryByText("from the example")).not.toBeInTheDocument();
      // Typing in a box takes its tag off before anything is saved.
      await userEvent.type(screen.getByLabelText("Wording of: Investment discussed"), "!");
      expect(screen.getAllByText("from the example")).toHaveLength(5);
    });

  it("is ready to run, with advice about Claude's wording that blocks nothing", async () => {
    showBuilder(fromExample());
    expect(await screen.findByText("Ready to run")).toBeInTheDocument();
    expect(screen.queryByLabelText("What this template still needs")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Worth a look"))
      .toHaveTextContent("Wording for Claude still says fractional operations executive.");
    expect(screen.getByRole("link", { name: "Start a session from this template" }))
      .toHaveAttribute("href", `/strategy?template=${TEMPLATE_ID}`);
  });

  it("drops the advice and the tag once Claude's wording is the practice's own", async () => {
    showBuilder(fromExample({
      example: { start_from: "operations_example", version: 2, unchanged_settings: [] } }));
    await screen.findByText(/Made from the Operations example/);
    expect(screen.queryByLabelText("Worth a look")).not.toBeInTheDocument();
    expect(screen.getAllByText("from the example")).toHaveLength(5);
  });

  it("marks the question that is never put to the prospect", async () => {
    showBuilder(fromExample());
    await screen.findByText(/Made from the Operations example/);
    expect(screen.getAllByText("not asked aloud")).toHaveLength(1);
  });

  it("shows none of this on a template built from blank", async () => {
    showBuilder(aBuilder({ ready: true, missing: [] }));
    expect(await screen.findByText("Ready to run")).toBeInTheDocument();
    expect(screen.queryByText(/Made from the Operations example/)).not.toBeInTheDocument();
    expect(screen.queryByText("from the example")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("Worth a look")).not.toBeInTheDocument();
    expect(screen.queryByText("not asked aloud")).not.toBeInTheDocument();
  });

  it("offers no session to someone who cannot edit, or from a template not ready",
    async () => {
      showBuilder(fromExample(), aMe({ role: "CF" }));
      await screen.findByText("Ready to run");
      expect(screen.queryByRole("link", { name: "Start a session from this template" }))
        .not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Dismiss" })).toBeInTheDocument();
    });
});

// ========================================================= the templates list

const SECTION = { code: "diagnostic", title: "Diagnostic", position: 3,
                  time_budget_minutes: 25, questions: [q("s4_done_right",
                    "How do you know a site was done right?")] };
const SEEDED: StrategyTemplateRow = {
  id: "t1", name: "Operations — focused", discipline: "operations", version: 1,
  is_default: true, archived_at: null, sessions: 0, sections: [SECTION] };
const BUILT: StrategyTemplateRow = {
  id: TEMPLATE_ID, name: "Our session", discipline: "operations", version: 1,
  is_default: false, archived_at: null, sessions: 0, sections: [SECTION],
  format: "v3", ready: false, missing: ["Ratings needs at least 2 rated items (it has 0)."] };

function showTemplates(rows: StrategyTemplateRow[], route = "/",
                       extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({ ...extra, "GET /api/strategy-templates/": rows });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<SessionTemplate me={aMe()} />, { route });
  return fetchMock;
}

describe("the templates screen", () => {
  it("gives a practice with no template two starts, a name already filled in, and no seed",
    async () => {
      const fetchMock = showTemplates([], "/", {
        "POST /api/strategy-template-builder/": () => ({ status: 201, body: aBuilder() }) });
      expect(await screen.findByText(/A strategy session runs from a template/))
        .toBeInTheDocument();
      expect(screen.queryByText("Loading the template…")).not.toBeInTheDocument();
      expect(screen.queryByRole("button", { name: "Restore from seed" }))
        .not.toBeInTheDocument();
      expect(screen.getByLabelText("Name for the new template")).toHaveValue("Strategy session");
      expect(screen.getByText(/A complete template you can run today/)).toBeInTheDocument();
      expect(screen.getByText(/The eight parts with nothing in them/)).toBeInTheDocument();
      // Nothing of their own to copy yet.
      expect(screen.queryByRole("button", { name: "Start from a copy" }))
        .not.toBeInTheDocument();
      // One click, with no typing.
      await userEvent.click(
        screen.getByRole("button", { name: "Start from the Operations example" }));
      await waitFor(() => expect(sent(fetchMock, "/api/strategy-template-builder/"))
        .toEqual([{ name: "Strategy session", start_from: "operations_example" }]));
    });

  it("starts blank without naming an example", async () => {
    const fetchMock = showTemplates([], "/", {
      "POST /api/strategy-template-builder/": () => ({ status: 201, body: aBuilder() }) });
    const name = await screen.findByLabelText("Name for the new template");
    await userEvent.clear(name);
    expect(screen.getByRole("button", { name: "Start blank" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Start from the Operations example" }))
      .toBeDisabled();
    await userEvent.type(name, "Our session");
    await userEvent.click(screen.getByRole("button", { name: "Start blank" }));
    await waitFor(() => expect(sent(fetchMock, "/api/strategy-template-builder/"))
      .toEqual([{ name: "Our session" }]));
  });

  it("says why when a start is refused, and keeps the name", async () => {
    showTemplates([], "/", {
      "POST /api/strategy-template-builder/": () => ({
        status: 409, body: { detail: "There is already a template called “Strategy session”." } }) });
    await userEvent.click(
      await screen.findByRole("button", { name: "Start from the Operations example" }));
    expect(await screen.findByText(/There is already a template called/)).toBeInTheDocument();
    expect(screen.getByLabelText("Name for the new template")).toHaveValue("Strategy session");
  });

  it("offers every practice the same two starts, and a copy of a template it built",
    async () => {
      const fetchMock = showTemplates([SEEDED, BUILT], "/", {
        "POST /api/strategy-template-builder/": () => ({ status: 201, body: aBuilder() }),
        [`POST /api/strategy-templates/${TEMPLATE_ID}/duplicate/`]:
          () => ({ status: 201, body: { ...BUILT, id: "copy" } }) });
      expect(await screen.findByText("Start from")).toBeInTheDocument();
      // On the list the name is theirs to type: "Strategy session" may be taken.
      expect(screen.getByLabelText("Name for the new template")).toHaveValue("");
      expect(screen.getByRole("button", { name: "Start from the Operations example" }))
        .toBeDisabled();
      // Only templates built here can be copied this way, not a seeded one.
      const copyOf = screen.getByLabelText("Template to copy");
      expect(within(copyOf).getAllByRole("option").map((o) => o.textContent))
        .toEqual([BUILT.name]);
      await userEvent.click(screen.getByRole("button", { name: "Start from a copy" }));
      await waitFor(() => expect(sent(fetchMock, "/duplicate/")).toEqual([{}]));
    });

  it("starts from the example on the list once it has a name", async () => {
    const fetchMock = showTemplates([SEEDED, BUILT], "/", {
      "POST /api/strategy-template-builder/": () => ({ status: 201, body: aBuilder() }) });
    await userEvent.type(await screen.findByLabelText("Name for the new template"), "Second");
    await userEvent.click(
      screen.getByRole("button", { name: "Start from the Operations example" }));
    await waitFor(() => expect(sent(fetchMock, "/api/strategy-template-builder/"))
      .toEqual([{ name: "Second", start_from: "operations_example" }]));
  });

  it("sends a builder template to the builder instead of the editor", async () => {
    showTemplates([SEEDED, BUILT], `/?template=${TEMPLATE_ID}`);
    const open = await screen.findByRole("link", { name: "Open the builder" });
    expect(open).toHaveAttribute("href", `/strategy/templates/${TEMPLATE_ID}/build`);
    expect(screen.getByText(/not ready to run/)).toBeInTheDocument();
    expect(screen.queryByLabelText("Wording of s4_done_right")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Save/ })).not.toBeInTheDocument();
    // It is still renamed, duplicated and archived here, and the seed is
    // still offered because this practice has a seeded template.
    expect(screen.getByRole("button", { name: "Rename" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore from seed" })).toBeInTheDocument();
  });

  it("does not offer the seed to a practice that only has its own templates", async () => {
    showTemplates([BUILT]);
    await screen.findByRole("link", { name: "Open the builder" });
    expect(screen.queryByRole("button", { name: "Restore from seed" })).not.toBeInTheDocument();
    expect(screen.queryByText(/Operations seed/)).not.toBeInTheDocument();
  });

  it("leaves a seeded template's editor as it was, with New template beside it", async () => {
    showTemplates([SEEDED, BUILT]);
    expect(await screen.findByLabelText("Wording of s4_done_right")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Restore from seed" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start blank" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Open the builder" })).not.toBeInTheDocument();
  });
});

describe("starting a session", () => {
  it("lists a builder template that is not ready, and will not choose it", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/strategy-templates/": [{ ...SEEDED, is_default: false }, BUILT],
      "GET /api/strategy-sessions/": [],
    }));
    renderRoute(<Sessions me={aMe()} />);
    const picker = await screen.findByLabelText("Template");
    const option = await within(picker).findByRole("option",
      { name: "Our session (not ready to run)" });
    expect(option).toBeDisabled();
    expect(picker).toHaveValue("t1");
  });

  it("tells a practice with no template to build one first", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/strategy-templates/": [],
                                     "GET /api/strategy-sessions/": [] }));
    renderRoute(<Sessions me={aMe()} />);
    expect(await screen.findByText(/has no strategy template yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Build one" }))
      .toHaveAttribute("href", "/strategy/template");
  });
});

// ============================================================== the live view

function aV3Session(overrides: Partial<StrategySessionRow> = {}): StrategySessionRow {
  return {
    id: SESSION_ID, state: "in_call", format: "v3",
    rating_scale: "1 is not yet, 10 is every week", diagnostic: { size: 3, most: 8 },
    template: { id: TEMPLATE_ID, name: "Our session" },
    contact: { id: "c1", name: "Dana Reyes" }, company: { id: "co1", name: "Acme Facilities" },
    visionary: null, integrator: null, owner: "Shawn",
    scheduled_at: null, started_at: "2026-10-05T12:00:00Z", budget_minutes: 55,
    current_section: "", current_section_at: null,
    precall_sent: true, precall_expires_at: "2026-11-04T14:00:00Z",
    precall_questions_sent_at: null, prep: null, pinned_questions: [], fractional_note: "",
    precall_default_intro: "Hi Dana,",
    mirror: { goal: "", unlocks: "" },
    proposed_mirror: { goal: "Two branches by spring.", unlocks: "Supervisor cover." },
    pdf_include_flags: { fractional_notes: false, mechanics: false,
                         diagnostic_observations: false, alignment_observation: false,
                         investment: false },
    has_pdf: false, converted_at: null, created_at: "2026-10-05T12:00:00Z",
    sections: [
      { code: "six_key_components", kind: "ratings", title: "Three things we rate",
        position: 1, time_budget_minutes: 5, questions: [
          q("r1", "Plan — Our plan is written down.", { response_schema: "rating_1_10",
                                                         label: "Plan" })] },
      { code: "diagnostic", kind: "diagnostic", title: "Diagnostic", position: 2,
        time_budget_minutes: 15, questions: [] },
      { code: "mirror", kind: "mirror", title: "The mirror and where they want to go",
        position: 3, time_budget_minutes: 10, questions: [
          q("m1", "Three years from now, what does Acme look like?")] },
      { code: "strategy_map", kind: "map", title: "Strategy Map", position: 4,
        time_budget_minutes: 10, questions: [] },
    ],
    answers: [], map_rows: [], path_notes: [],
    diagnostic_proposals: [
      { id: "d1", rule: "growth", rule_label: "They mentioned growth or expansion",
        basis: "a second branch", prompt: "What has to be true before the branch opens?",
        state: "proposed", question_key: "", from_ai: true },
      { id: "d2", rule: "manual", rule_label: "Added by hand during the session", basis: "",
        prompt: "Who decides on price?", state: "accepted", question_key: "dx_1",
        from_ai: false },
    ],
    six_key_components: { scores: [], ratings: {}, answered: 0, of: 1, average: null,
                          complete: false, lowest: null },
    must_ask: { outstanding: [], answered: 0, of: 0 },
    ...overrides,
  } as StrategySessionRow;
}

function showSession(session = aV3Session(), me = aMe(), extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    [`GET /api/strategy-sessions/${SESSION_ID}/conversion-preview/`]: { rows: [] },
    "GET /api/strategy-sessions/": session,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<SessionDetail me={me} />, { path: "/strategy/:id",
                                           route: `/strategy/${SESSION_ID}` });
  return fetchMock;
}

describe("a v3 session in the live view", () => {
  it("asks a section of the practice's own where the template put it, with a note field",
    async () => {
      const session = aV3Session();
      session.sections!.splice(2, 0, {
        code: "custom_ab12cd34", kind: "custom", title: "Leadership bench", position: 3,
        time_budget_minutes: 5, questions: [
          q("c1", "Who runs the day to day?", { has_fractional_note: true }),
          q("c2", "Where does hiring stall?", { response_schema: "diagnostic_triple",
                                                has_fractional_note: true }),
          q("c3", "Org chart shared", { response_schema: "agreed_note",
                                        has_fractional_note: true })] });
      showSession(session);
      const heading = await screen.findByText("Leadership bench", { selector: "span[id]" });
      expect(heading).toHaveAttribute("id", "section-custom_ab12cd34");
      // Between the diagnostic and the mirror, as the template has it.
      const titles = Array.from(document.querySelectorAll("span[id^='section-']"))
        .map((el) => el.id);
      expect(titles.indexOf("section-custom_ab12cd34"))
        .toBe(titles.indexOf("section-diagnostic") + 1);
      expect(screen.getByLabelText("Private note — Who runs the day to day?"))
        .toBeInTheDocument();
      expect(screen.getByLabelText("What they said — Where does hiring stall?"))
        .toBeInTheDocument();
      expect(screen.getByLabelText("Agreed — Org chart shared")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: "Start Leadership bench" })).toBeInTheDocument();
    });

  it("says the template's scale above the ratings, once", async () => {
    showSession();
    expect(await screen.findByText("Rate each one from 1 to 10 — 1 is not yet, 10 is every "
      + "week.")).toBeInTheDocument();
    expect(screen.getAllByText(/1 is not yet/)).toHaveLength(1);
  });

  it("names the ratings summary after the template's own section and labels", async () => {
    const rated = aV3Session();
    rated.six_key_components = { scores: [{ key: "r1", rating: 4, comment: "",
                                            answered_by: "fractional" }],
      ratings: { r1: 4 }, answered: 1, of: 1, average: 4, complete: true, lowest: "r1" };
    showSession(rated);
    await screen.findByText("Look here first");
    expect(screen.queryByText("Six Key Components")).not.toBeInTheDocument();
    expect(screen.getAllByText("Three things we rate").length).toBeGreaterThan(1);
    expect(screen.getByText("Plan")).toBeInTheDocument();
  });

  it("shows the diagnostic tray with what is in the session and what is proposed",
    async () => {
      showSession();
      const accepted = await screen.findByRole("list", { name: "Accepted diagnostic questions" });
      expect(within(accepted).getByText(/Who decides on price\?/)).toBeInTheDocument();
      expect(within(accepted).getByText("added by hand")).toBeInTheDocument();
      expect(screen.getByText(/1 in the session \(this template starts with 3; 8 at most\)/))
        .toBeInTheDocument();
      expect(screen.getByLabelText(
        "Proposed question: What has to be true before the branch opens?")).toBeInTheDocument();
      expect(screen.queryByText(/five fixed questions/)).not.toBeInTheDocument();
      expect(screen.queryByText("Nothing to capture here.")).not.toBeInTheDocument();
    });

  it("adds a question typed on the call", async () => {
    const fetchMock = showSession(aV3Session(), aMe(), {
      "POST /api/strategy-diagnostic-proposals/": () => ({ status: 201, body: {} }) });
    const box = await screen.findByLabelText("A diagnostic question of your own");
    const add = screen.getByRole("button", { name: "Add a question" });
    expect(add).toBeDisabled();
    await userEvent.type(box, "Who signs the contracts?");
    await userEvent.click(add);
    await waitFor(() => expect(box).toHaveValue(""));
    expect(sent(fetchMock, "/api/strategy-diagnostic-proposals/")).toEqual([
      { session: SESSION_ID, prompt: "Who signs the contracts?" }]);
  });

  it("proposes from the ratings only once two are taken", async () => {
    showSession();
    expect(await screen.findByRole("button", { name: "Propose from the ratings" }))
      .toBeDisabled();
  });

  it("sends from_ratings when the ratings are in, and says when nothing is new", async () => {
    const rated = aV3Session();
    rated.six_key_components = { ...rated.six_key_components!, answered: 2 };
    const fetchMock = showSession(rated, aMe(), {
      [`POST /api/strategy-sessions/${SESSION_ID}/propose-diagnostic/`]: { proposed: [] } });
    await userEvent.click(await screen.findByRole("button", { name: "Propose from the ratings" }));
    expect(await screen.findByText("Nothing new to propose from what is there."))
      .toBeInTheDocument();
    expect(sent(fetchMock, "propose-diagnostic/")).toEqual([{ from_ratings: true }]);
    await userEvent.click(screen.getByRole("button", { name: "Propose more" }));
    await waitFor(() => expect(sent(fetchMock, "propose-diagnostic/")).toHaveLength(2));
    expect(sent(fetchMock, "propose-diagnostic/")[1]).toEqual({});
  });

  it("stops offering to add at the session's ceiling", async () => {
    const full = aV3Session({ diagnostic: { size: 3, most: 1 } });
    showSession(full);
    expect(await screen.findByText(/holds 1 diagnostic questions, the most it can/))
      .toBeInTheDocument();
    expect(screen.getByLabelText("A diagnostic question of your own")).toBeDisabled();
    expect(screen.getByRole("button", { name: /^Accept "What has to be true/ })).toBeDisabled();
  });

  it("reads the mirror back after its own questions", async () => {
    showSession();
    const question = await screen.findByText("Three years from now, what does Acme look like?");
    const draft = screen.getByText("Two branches by spring.");
    expect(question.compareDocumentPosition(draft) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });

  it("caps the map at five, as a focused session does", async () => {
    showSession();
    expect(await screen.findByText(/The map — 0 of 5 rows/)).toBeInTheDocument();
  });

  it("says a full map is full instead of drafting", async () => {
    showSession(aV3Session(), aMe(), {
      [`POST /api/strategy-sessions/${SESSION_ID}/draft-rows/`]: {
        drafted: [], detail: "The map holds 5 rows and it is full. Remove one, or "
          + "Consolidate, before drafting more." } });
    await userEvent.click(await screen.findByRole("button", { name: /Draft rows/ }));
    expect(await screen.findByText(/it is full/)).toBeInTheDocument();
  });

  it("gives an assistant no diagnostic controls", async () => {
    showSession(aV3Session({ diagnostic_proposals: [] }), aMe({ role: "VA" }));
    await screen.findByText("Three years from now, what does Acme look like?");
    expect(screen.queryByRole("button", { name: "Add a question" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Propose/ })).not.toBeInTheDocument();
  });
});
