import { screen, waitFor, within } from "@testing-library/react";
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
});
