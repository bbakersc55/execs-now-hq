import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Evaluation, RunFull, ToolDefinition } from "../lib/tools";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { ToolEditorScreen, ToolRunScreen, ToolsScreen } from "./Tools";

const DEF: ToolDefinition = {
  sections: [{ title: "The process", fields: [
    { key: "process", label: "Process", type: "text" },
    { key: "steps", label: "Steps, in order", type: "table", columns: [
      { key: "step", label: "Step", type: "text" },
      { key: "capacity", label: "Capacity a week (units)", type: "number" },
      { key: "load", label: "Load", type: "computed", format: "percent",
        formula: "capacity" }] }] }],
  results: [{ key: "constraint", label: "The constraint", formula: "argmax(steps.step, steps.load)",
    format: "text" }],
  actions: ["import_sop"],
};

const EVAL: Evaluation = {
  values: {}, computed: {},
  tables: { steps: [{ load: { value: 146.7, text: "146.7%", error: "" } }] },
  results: [{ key: "constraint", label: "The constraint", format: "text", value: "Form",
    text: "Form", error: "", note: "", numeric: false },
  { key: "output", label: "The process can produce a week", format: "number", value: 54.5,
    text: "54.5", error: "", note: "", numeric: true }],
};

function aRun(over: Partial<RunFull> = {}): RunFull {
  return {
    id: "r1", name: "Order to shipment", tool_name: "Bottleneck finder", tool_key: "ops_bottleneck",
    tool_id: null, run_date: "2026-11-02", company: { id: "c1", name: "Acme Fasteners",
      is_practice: false }, shared_with_client: false, updated_at: "2026-11-02T10:00:00Z",
    may_edit: true, definition: DEF, values: { process: "Order to shipment",
      steps: [{ step: "Form", capacity: "60" }] }, evaluation: EVAL,
    choices: { people: ["Marvin Martian"], kpis: [{ id: "k1", name: "Output", cadence: "weekly" }],
      sop_sources: [{ id: "note:n1", label: "SOP draft: Picking" }], has_plan: true },
    ...over,
  };
}

const runRoute = { path: "/tool-runs/:id", route: "/tool-runs/r1" };

// 2026-11-14 (E): how to use a tool, its sample, the drawn org chart, teams as attendees.
const HOW: Partial<ToolDefinition> = {
  how_to: ["Name the process and add its steps.", "Put each step's capacity.", "Read the constraint."],
  sample: { process: "Order to shipment", steps: [{ step: "Make the parts", capacity: 80 }] },
};
const SAYS: Evaluation = { ...EVAL, results: [{ ...EVAL.results[0],
  says: "Form is the constraint: it holds up the whole process." }] };

const ORG: ToolDefinition = {
  sections: [{ title: "Seats", fields: [{ key: "seats", label: "Seats", type: "table", columns: [
    { key: "seat", label: "Seat", type: "text" }, { key: "person", label: "Who is in it", type: "person" }] }] }],
  results: [], views: [{ type: "org_chart", table: "seats", name: "seat", parent: "reports_to", person: "person" }],
};
const ORG_EVAL: Evaluation = { values: {}, computed: {}, tables: { seats: [{}] }, results: [],
  views: [{ type: "org_chart", svg: "<svg xmlns='http://www.w3.org/2000/svg' width='800' height='300'></svg>",
    width: 800, height: 300, label: "Org chart: 1 seat, 0 open, 0 with a no." }] };

const MEET: ToolDefinition = {
  sections: [{ title: "Standing meetings", fields: [{ key: "meetings", label: "Meetings", type: "table",
    columns: [{ key: "name", label: "Meeting", type: "text" },
      { key: "attendees", label: "Who attends", type: "people" }] }] }],
  results: [], views: [{ type: "cadence", table: "meetings", agenda: "agenda" }], actions: ["calendar"],
};
const TEAMS = [{ name: "Sales", entry: "Team: Sales", shown: "Sales team (Sam Sales, Sue Seller)",
  members: ["Sam Sales", "Sue Seller"] }];

describe("tools (P12)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("a run: results first, its table with computed cells, and a save of what changed", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/tool-runs/r1/": aRun(),
      "POST /api/tools/evaluate/": EVAL,
      "PATCH /api/tool-runs/r1/": aRun({ values: { process: "Quoting", steps: [] } }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    const results = await screen.findByRole("region", { name: "Results" });
    expect(within(results).getByText("Form")).toBeInTheDocument();
    const table = screen.getByRole("table", { name: "Steps, in order" });
    expect(within(table).getByText("146.7%")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Saved" })).toBeDisabled();
    const process = screen.getByLabelText("Process");
    await user.clear(process);
    await user.type(process, "Quoting");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => {
      const call = fetchMock.calls.find((c) => c.method === "PATCH");
      expect((call?.body as { values: { process: string } }).values.process).toBe("Quoting");
    });
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute("href", "/api/tool-runs/r1/files/pdf/");
    expect(screen.getByRole("button", { name: "Import steps from an SOP" })).toBeInTheDocument();
  });

  it("send a result to a KPI offers only numbers", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/tool-runs/r1/": aRun(),
      "POST /api/tool-runs/r1/reading/": () => ({ status: 201, body: { value: "54.5" } }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    await user.click(await screen.findByRole("button", { name: "Send a result to a KPI" }));
    const result = screen.getByLabelText("Result");
    expect(within(result).queryByText(/The constraint/)).toBeNull();
    await user.click(screen.getByRole("button", { name: "Send it" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/reading/"))?.body)
      .toMatchObject({ result: "output", kpi: "k1" }));
    expect(await screen.findByText(/marked "From a tool"/)).toBeInTheDocument();
  });

  it("Start an SOP brainstorm opens a real brainstorm with the run as its source (P10)", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/tool-runs/r1/": aRun(),
      "POST /api/tool-runs/r1/sop-brainstorm/": () => ({ status: 201,
        body: { brainstorm: "b9", title: "SOP from Order to shipment" } }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    await user.click(await screen.findByRole("button", { name: "Start an SOP brainstorm" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.endsWith("/sop-brainstorm/"))).toBe(true));
    // It leaves the run for /sop-brainstorms/b9, which this test's router doesn't draw.
    await waitFor(() => expect(screen.queryByRole("button", { name: "Start an SOP brainstorm" })).toBeNull());
  });

  it("Import steps from an SOP lists the studio's SOPs (P10)", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/tool-runs/r1/": aRun({ choices: { ...aRun().choices!,
      sop_sources: [{ id: "sop:s1", label: "SOP: Receiving an order" }, { id: "note:n1", label: "SOP draft: Picking" }] } }),
      "POST /api/tool-runs/r1/import-sop/": () => ({ body: { imported: 3, run: aRun() } }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    await user.click(await screen.findByRole("button", { name: "Import steps from an SOP" }));
    const dialog = screen.getByRole("dialog", { name: "Import steps from an SOP" });
    await user.selectOptions(within(dialog).getByLabelText("SOP"), "sop:s1");
    await user.click(within(dialog).getByRole("button", { name: "Add its steps" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/import-sop/"))?.body)
      .toEqual({ source: "sop:s1" }));
  });

  it("the client owner reads a shared run, with nothing to change", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/tool-runs/r1/": aRun({ may_edit: false,
      choices: undefined, shared_with_client: true }) }));
    renderRoute(<ToolRunScreen me={aMe({ role: "FCC", client_company: "c1" })} />, runRoute);
    expect(await screen.findByRole("region", { name: "Results" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Save/ })).toBeNull();
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button", { name: "Tasks from flagged rows" })).toBeNull();
  });

  it("the shelf: a tool runs for the company chosen", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/tools/": { tools: [{ ref: "ops_bottleneck", name: "Bottleneck finder",
        description: "Steps and capacity", shipped: true }], recent: [], may_build: true },
      "GET /api/plans/": { plans: [{ id: "c1", name: "Acme Fasteners", is_practice: false }] },
      "POST /api/tool-runs/": () => ({ status: 201, body: aRun() }),
      "GET /api/tool-runs/r1/": aRun() });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ToolsScreen me={aMe({ role: "FF" })} />, { path: "/tools", route: "/tools" });
    expect(await screen.findByRole("button", { name: "Duplicate to edit" })).toBeInTheDocument();
    await user.click(await screen.findByRole("button", { name: "Run it" }));
    await user.selectOptions(await screen.findByLabelText("For"), "c1");
    await user.click(screen.getByRole("button", { name: "Start the run" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ company: "c1", tool: "ops_bottleneck" }));
  });

  it("New tool: the price first, then Claude's proposal in the editor, unsaved", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/tools/builder/": { estimate_usd: "0.0912", refused: "", used_today: 0, cap: 20 },
      "GET /api/tools/": { tools: [], recent: [], may_build: true },
      "POST /api/tools/builder/": { name: "Quote turnaround", description: "", errors: [],
        definition: { sections: [{ title: "Quotes", fields: [
          { key: "asked", label: "Asked", type: "number" }] }], results: [] } },
      "POST /api/tools/validate/": { errors: [] },
      "POST /api/tools/evaluate/": { values: {}, computed: {}, tables: {}, results: [] } });
    vi.stubGlobal("fetch", fetchMock);
    const { Routes, Route } = await import("react-router-dom");
    renderRoute(<Routes><Route path="/tools" element={<ToolsScreen me={aMe({ role: "FF" })} />} />
      <Route path="/tools/:ref/edit" element={<ToolEditorScreen />} /></Routes>,
    { path: "*", route: "/tools" });
    await user.click(await screen.findByRole("button", { name: "New tool" }));
    const press = await screen.findByRole("button", { name: "Propose it with Claude (about $0.09)" });
    expect(press).toBeDisabled();
    await user.type(screen.getByLabelText("The worksheet"), "Quotes asked and sent each week");
    await user.click(press);
    expect(await screen.findByText("Claude's proposal. Nothing is saved until you save it."))
      .toBeInTheDocument();
    expect(screen.getByDisplayValue("Quote turnaround")).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.method === "POST" && c.url.endsWith("/api/tools/"))).toBe(false);
  });

  it("the editor marks a bad formula where it is and keeps Save off", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/tools/t1/": { key: "", id: "t1", name: "Margin", description: "", shipped: false,
        definition: { sections: [{ title: "Numbers", fields: [
          { key: "m", label: "Margin", type: "computed", formula: "price -", format: "percent" }] }],
          results: [] } },
      "POST /api/tools/validate/": { errors: [{ where: "sections.0.fields.0",
        message: "Margin: The formula stops too soon." }] } }));
    renderRoute(<ToolEditorScreen />, { path: "/tools/:ref/edit", route: "/tools/t1/edit" });
    expect(await screen.findByText("Margin: The formula stops too soon.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save as our tool" })).toBeDisabled();
    expect(screen.getByLabelText("Formula for Margin")).toHaveValue("price -");
  });

  it("calendar events on the demo: what it would make, and a file to download", async () => {
    const user = userEvent.setup();
    const cadence = aRun({ definition: { ...DEF, actions: ["calendar"] } });
    vi.stubGlobal("fetch", mockApi({ "GET /api/tool-runs/r1/files/calendar/": { demo: true,
      connected: false, events: [{ name: "Weekly leadership meeting", cadence: "Weekly",
        day: "Monday", first: "2026-11-16", time: "08:30", minutes: 60,
        rrule: "FREQ=WEEKLY;BYDAY=MO", attendees: ["Wiley Coyote"], agenda: [], note: "" }] },
    "GET /api/tool-runs/r1/": cadence }));
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    await user.click(await screen.findByRole("button", { name: "Calendar events" }));
    expect(await screen.findByText(/These are the events it would make/)).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Events it would make" }))
      .toHaveTextContent("Weekly leadership meeting");
    expect(screen.queryByRole("button", { name: "Add them to my calendar" })).toBeNull();
    expect(screen.getByRole("link", { name: "Download a calendar file" }))
      .toHaveAttribute("href", "/api/tool-runs/r1/files/ics/");
  });

  it("How to use this: open on an empty run, shut on one with values, and each result says what it means", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "GET /api/tool-runs/r1/": aRun({
      definition: { ...DEF, ...HOW }, values: { process: "", steps: [] }, evaluation: SAYS }) }));
    const first = renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    const toggle = await screen.findByRole("button", { name: /How to use this/ });
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    expect(screen.getByText("Put each step's capacity.")).toBeInTheDocument();
    expect(within(screen.getByRole("region", { name: "Results" }))
      .getByText("Form is the constraint: it holds up the whole process.")).toBeInTheDocument();
    first.unmount();

    vi.stubGlobal("fetch", mockApi({ "GET /api/tool-runs/r1/": aRun({ definition: { ...DEF, ...HOW } }) }));
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    const shut = await screen.findByRole("button", { name: /How to use this/ });
    expect(shut).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Put each step's capacity.")).toBeNull();
    await user.click(shut);
    expect(screen.getByText("Put each step's capacity.")).toBeInTheDocument();
  });

  it("Load sample values fills an empty run at once, unsaved until Save", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    const fetchMock = mockApi({ "GET /api/tool-runs/r1/": aRun({ definition: { ...DEF, ...HOW },
      values: { process: "", steps: [] } }), "POST /api/tools/evaluate/": EVAL,
      "PATCH /api/tool-runs/r1/": aRun() });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    await user.click(await screen.findByRole("button", { name: "Load sample values" }));
    expect(screen.getByLabelText("Process")).toHaveValue("Order to shipment");
    expect(screen.getByText(/Nothing is saved until you press Save/)).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.method === "PATCH")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body).toEqual({
      values: HOW.sample }));
    expect(confirm).not.toHaveBeenCalled();
  });

  it("Load sample values asks inline first when the run has values", async () => {
    const user = userEvent.setup();
    const confirm = vi.fn(() => true);
    vi.stubGlobal("confirm", confirm);
    vi.stubGlobal("fetch", mockApi({ "GET /api/tool-runs/r1/": aRun({ definition: { ...DEF, ...HOW } }),
      "POST /api/tools/evaluate/": EVAL }));
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    await user.click(await screen.findByRole("button", { name: "Load sample values" }));
    const ask = screen.getByRole("group", { name: "Replace with the sample" });
    expect(ask).toHaveTextContent("Replace what's here with the sample?");
    await user.click(within(ask).getByRole("button", { name: "Keep what's here" }));
    expect(screen.getByLabelText("Process")).toHaveValue("Order to shipment");
    expect(screen.getByRole("button", { name: "Saved" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Load sample values" }));
    await user.click(screen.getByRole("button", { name: "Replace" }));
    expect(screen.getByLabelText("Step, row 1")).toHaveValue("Make the parts");
    expect(screen.getByRole("button", { name: "Save" })).toBeEnabled();
    expect(confirm).not.toHaveBeenCalled();
  });

  it("the org chart is the server's drawing, with zoom in, zoom out and Fit", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "GET /api/tool-runs/r1/": aRun({ definition: ORG,
      values: { seats: [{ seat: "Owner", person: "Olive Owner" }] }, evaluation: ORG_EVAL }) }));
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    const chart = await screen.findByRole("region", { name: "The chart" });
    const img = within(chart).getByRole("img", { name: "Org chart: 1 seat, 0 open, 0 with a no." });
    expect(img.getAttribute("src")).toMatch(/^data:image\/svg\+xml/);
    const zoom = within(chart).getByRole("group", { name: "Zoom the chart" });
    expect(zoom).toHaveTextContent("100%");
    await user.click(within(zoom).getByRole("button", { name: "Zoom in" }));
    expect(zoom).toHaveTextContent("125%");
    expect(img).toHaveAttribute("width", "1000");
    await user.click(within(zoom).getByRole("button", { name: "Zoom out" }));
    await user.click(within(zoom).getByRole("button", { name: "Zoom out" }));
    expect(zoom).toHaveTextContent("80%");
    expect(img).toHaveAttribute("width", "640");
    await user.click(within(zoom).getByRole("button", { name: "Fit" }));
    expect(zoom).toHaveTextContent("100%");
  });

  it("who attends takes several people and whole teams, as chips", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/tool-runs/r1/": aRun({ definition: MEET, teams: TEAMS,
      values: { meetings: [{ name: "Weekly sales huddle", attendees: ["Mia Member"] }] },
      evaluation: { values: {}, computed: {}, tables: { meetings: [{}] }, results: [] } }),
      "POST /api/tools/evaluate/": { values: {}, computed: {}, tables: { meetings: [{}] }, results: [] },
      "PATCH /api/tool-runs/r1/": () => ({ body: aRun({ definition: MEET, teams: TEAMS }) }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ToolRunScreen me={aMe({ role: "FF" })} />, runRoute);
    const who = await screen.findByLabelText("Who attends, row 1");
    expect(document.querySelector("#tl-attendees option[value='Team: Sales']")).not.toBeNull();
    expect(document.querySelector("#tl-attendees option[value='Marvin Martian']")).not.toBeNull();
    // Picked from the list: added at once.
    fireEvent.change(who, { target: { value: "Team: Sales" } });
    expect(screen.getByRole("button", { name: "Remove Team: Sales from Who attends, row 1" })).toBeInTheDocument();
    // Typed, with Enter: free text is fine too.
    await user.type(who, "Bo Chen{Enter}");
    expect(who).toHaveValue("");
    const cadence = screen.getByRole("region", { name: "The cadence on one page" });
    expect(cadence).toHaveTextContent("Mia Member, Sales team (Sam Sales, Sue Seller), Bo Chen");
    await user.click(screen.getByRole("button", { name: "Remove Mia Member from Who attends, row 1" }));
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect((fetchMock.calls.find((c) => c.method === "PATCH")?.body as {
      values: { meetings: { attendees: string[] }[] } }).values.meetings[0].attendees)
      .toEqual(["Team: Sales", "Bo Chen"]));
  });
});
