import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SopsForKpi } from "../components/SopsForKpi";
import { NoteDetail } from "./NoteDetail";
import { SopFull, SopPortal, SopSummary } from "../lib/sops";
import { aMe, aNote, NOTE_ID } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { CompanySopsCard, SopScreen, SopsScreen, SopsShelfCard } from "./Sops";

const ACME = { id: "c1", name: "Acme Fasteners", is_practice: false };
const STARK = { id: "c2", name: "Stark Tool & Die", is_practice: false };

function row(over: Partial<SopSummary> = {}): SopSummary {
  return { id: "s1", title: "Receiving an order", status: "published", category: "Shipping",
    version: 1, company: ACME, owner: "Marvin Martian", review_date: "2027-02-01",
    published_at: "2026-11-01T10:00:00Z", updated_at: "2026-11-01T10:00:00Z", from_ai_app: false,
    reads: { asked: 12, read: 7 }, ...over };
}

const LIST = { may_create: true, sops: [
  row(),
  row({ id: "s2", title: "Cycle count", status: "draft", version: 0, reads: null, category: "Inventory" }),
  row({ id: "s3", title: "Old forklift check", status: "archived", category: "Safety" }),
  row({ id: "s4", title: "Quoting a job", company: STARK, category: "Sales", reads: { asked: 3, read: 3 } }),
] };

function full(over: Partial<SopFull> = {}): SopFull {
  return {
    ...row({ status: "draft", version: 0, reads: null }),
    purpose: "Every order checked in the day it lands.", applies_when: "", roles: [{ name: "Receiver", does: "Checks the order" }],
    steps: [{ text: "Count the cartons.", role: "Receiver", warning: "", images: [] }],
    sections: [{ title: "Records", body: "" }], process_map: "", map_svg: null, owner_id: null,
    audience: "company", teams: [], people: [], kpis: [], attachments: [], versions: [],
    unpublished_changes: true, reads: null, comments: [], brainstorms: [],
    may: { drafts: true, publishes: true, sees_reads: true, reminds: true, is_client: false,
      publish: true, edit: true },
    hints: { purpose: "What this procedure is for." }, last_version: 0,
    choices: { owners: [{ id: "u1", name: "Marvin Martian", side: "client" }], teams: [],
      people: [], kpis: [{ id: "k1", name: "On-time shipments" }] },
    ...over,
  };
}

const READS = { asked: 12, read: 7, number: 1, read_by: "2026-11-08",
  outstanding: [{ membership: "m8", name: "Daffy Duckworth" }, { membership: "m9", name: "Elmer Fudd" }],
  readers: [{ membership: "m1", name: "Marvin Martian", at: "2026-11-02T10:00:00Z", version: 1, late: false },
    { membership: "m2", name: "Porky Pig", at: "2026-11-10T10:00:00Z", version: 1, late: true }] };

function portal(over: Partial<SopPortal> = {}): SopPortal {
  return { id: "s1", title: "Receiving an order", version: 1, published_at: "2026-11-01T10:00:00Z",
    change_note: "First version.", minor: false, purpose: "Every order checked in.", applies_when: "",
    roles: [{ name: "Receiver", does: "Checks it" }],
    steps: [{ text: "Count the cartons.", role: "Receiver", warning: "Lift with your legs.", images: ["a1"] }],
    sections: [], owner: "Marvin Martian", category: "Shipping", review_date: null, kpis: [],
    map_svg: "<svg xmlns='http://www.w3.org/2000/svg'></svg>",
    attachments: [{ id: "a1", name: "carton.jpg", kind: "image", url: "/api/sops/s1/attachments/a1/" }],
    asked: true, read: false, read_at: null, read_version: null, read_by: "2026-11-08",
    may: { drafts: false, publishes: false, sees_reads: false, reminds: false, is_client: true },
    ...over };
}

const sopRoute = { path: "/sops/:id", route: "/sops/s1" };

describe("the SOP studio (P10)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists every SOP by client, with search and filters, archived ones hidden until asked", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({ "GET /api/sops/": LIST }));
    renderRoute(<SopsScreen me={aMe({ role: "FF" })} />);
    const acme = await screen.findByRole("region", { name: "SOPs for Acme Fasteners" });
    expect(within(acme).getByText("Receiving an order")).toBeInTheDocument();
    expect(within(acme).getByText(/7 of 12 read/)).toBeInTheDocument();
    expect(screen.queryByText("Old forklift check")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "SOPs for Stark Tool & Die" })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Status"), "archived");
    expect(screen.getByText("Old forklift check")).toBeInTheDocument();
    expect(screen.queryByText("Receiving an order")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Status"), "all");
    await user.selectOptions(screen.getByLabelText("Client"), "c2");
    expect(screen.getByText("Quoting a job")).toBeInTheDocument();
    expect(screen.queryByText("Cycle count")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Client"), "");
    await user.selectOptions(screen.getByLabelText("Category"), "Inventory");
    expect(screen.getByText("Cycle count")).toBeInTheDocument();
    expect(screen.queryByText("Quoting a job")).not.toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("Category"), "");
    await user.type(screen.getByLabelText("Search SOPs"), "quot");
    expect(screen.getByText("Quoting a job")).toBeInTheDocument();
    expect(screen.queryByText("Cycle count")).not.toBeInTheDocument();
  });

  it("the Command Center's shelf lists them, with New SOP and All SOPs", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/sops/": LIST }));
    renderRoute(<SopsShelfCard />);
    expect(await screen.findByText("Receiving an order")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "All SOPs" })).toHaveAttribute("href", "/sops");
    expect(screen.getByRole("button", { name: "New SOP" })).toBeInTheDocument();
  });

  it("New SOP makes a draft for the chosen company and opens it", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/sops/": LIST,
      "GET /api/plans/": { plans: [{ id: "c1", name: "Acme Fasteners", is_practice: false },
        { id: "practice", name: "Summit", is_practice: true }] },
      "POST /api/sops/": () => ({ status: 201, body: full() }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopsScreen me={aMe({ role: "CF" })} />);
    await user.click(await screen.findByRole("button", { name: "New SOP" }));
    const dialog = screen.getByRole("dialog", { name: "New SOP" });
    await user.type(within(dialog).getByLabelText("Title"), "Receiving an order");
    await user.selectOptions(within(dialog).getByLabelText("For"), "c1");
    expect(within(dialog).getByRole("option", { name: "Our practice" })).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Make the draft" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ company: "c1", title: "Receiving an order" }));
  });

  it("the editor saves the working copy, and the first publish asks for no change note", async () => {
    const user = userEvent.setup();
    let saved: Record<string, unknown> = {};
    const fetchMock = mockApi({
      "GET /api/sops/s1/": full(),
      "PATCH /api/sops/s1/": (body: unknown) => { saved = body as Record<string, unknown>;
        return { body: full({ title: String(saved.title), steps: saved.steps as SopFull["steps"] }) }; },
      "POST /api/sops/s1/publish/": () => ({ body: full({ status: "published", version: 1,
        unpublished_changes: false, reads: { ...READS, read: 0, readers: [] } }) }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopScreen me={aMe({ role: "FF" })} />, sopRoute);
    expect(await screen.findByPlaceholderText("What this procedure is for.")).toBeInTheDocument();
    const title = screen.getByLabelText("Title");
    await user.clear(title);
    await user.type(title, "Receiving and checking an order");
    await user.click(screen.getByRole("button", { name: "Add a step" }));
    await user.type(screen.getByLabelText("Step 2"), "Sign the delivery note.");
    await user.selectOptions(screen.getByLabelText("Owner"), "u1");
    await user.click(screen.getByRole("checkbox", { name: "On-time shipments" }));
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() => expect(saved.title).toBe("Receiving and checking an order"));
    expect((saved.steps as { text: string }[]).map((s) => s.text))
      .toEqual(["Count the cartons.", "Sign the delivery note."]);
    expect(saved.owner).toBe("u1");
    expect(saved.kpis).toEqual(["k1"]);
    expect(await screen.findByText("Saved.")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = screen.getByRole("dialog", { name: "Publish" });
    expect(within(dialog).getByText("Publish version 1")).toBeInTheDocument();
    expect(within(dialog).queryByLabelText("What changed")).not.toBeInTheDocument();
    expect(within(dialog).queryByText(/Minor change/)).not.toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Publish" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/publish/"))?.body)
      .toEqual({ change_note: "", minor: false }));
  });

  it("a later publish needs a line on what changed, and can be a minor change", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/sops/s1/": full({ status: "published", version: 2, reads: READS,
        versions: [{ number: 2, change_note: "Added the scale.", minor: false, published_at: "2026-11-05T10:00:00Z",
          published_by: "Bryan Baker", read_by: "2026-11-12" }] }),
      "POST /api/sops/s1/publish/": () => ({ body: full({ status: "published", version: 3, unpublished_changes: false }) }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopScreen me={aMe({ role: "CF" })} />, sopRoute);
    expect(await screen.findByText(/Changes not published yet/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PDF of version 2" })).toHaveAttribute("href", "/api/sops/s1/files/pdf/?version=2");
    await user.click(screen.getByRole("button", { name: "Publish" }));
    const dialog = screen.getByRole("dialog", { name: "Publish" });
    expect(within(dialog).getByText("Publish version 3")).toBeInTheDocument();
    const go = within(dialog).getByRole("button", { name: "Publish" });
    expect(go).toBeDisabled();
    await user.type(within(dialog).getByLabelText("What changed"), "Fixed a typo.");
    await user.click(within(dialog).getByRole("checkbox", { name: /Minor change \(doesn't ask people to read again\)/ }));
    await user.click(go);
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/publish/"))?.body)
      .toEqual({ change_note: "Fixed a typo.", minor: true }));
  });

  it("an assistant drafts but sees no Publish or Archive", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/sops/s1/": full({
      may: { drafts: true, publishes: false, sees_reads: true, reminds: false, is_client: false,
        publish: false, edit: true } }) }));
    renderRoute(<SopScreen me={aMe({ role: "VA" })} />, sopRoute);
    expect(await screen.findByRole("button", { name: "Add a step" })).toBeEnabled();
    expect(screen.queryByRole("button", { name: "Publish" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Archive" })).not.toBeInTheDocument();
    expect(screen.getByRole("link", { name: "PDF" })).toHaveAttribute("href", "/api/sops/s1/files/pdf/");
    expect(screen.getByRole("link", { name: "Word" })).toHaveAttribute("href", "/api/sops/s1/files/docx/");
  });

  it("who has read it: 7 of 12, the names outstanding, a late reader, and Remind", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "GET /api/sops/s1/": full({ status: "published", version: 1, reads: READS, unpublished_changes: false }),
      "POST /api/sops/s1/remind/": () => ({ status: 201, body: { drafted: 2, skipped: 0 } }) }));
    renderRoute(<SopScreen me={aMe({ role: "FF" })} />, sopRoute);
    const panel = await screen.findByRole("region", { name: "Who has read it" });
    expect(within(panel).getByText("7 of 12 read")).toBeInTheDocument();
    expect(panel).toHaveTextContent("Not read yet: Daffy Duckworth, Elmer Fudd");
    expect(within(panel).getByText("late")).toBeInTheDocument();
    await user.click(within(panel).getByRole("button", { name: "Remind the 2 who haven't read it" }));
    expect(await within(panel).findByText(/2 reminders drafted, waiting in the Sending queue/)).toBeInTheDocument();
    expect(within(panel).getByRole("link", { name: "Open the Sending queue" })).toHaveAttribute("href", "/sending-queue");
  });

  it("the portal: read it, tick Read and understood, and a new version asks again", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/sops/s1/": portal(),
      "POST /api/sops/s1/ack/": () => ({ body: { acknowledged_at: "2026-11-03T10:00:00Z", version: 1,
        late: false, sop: portal({ read: true, read_at: "2026-11-03T10:00:00Z", read_version: 1 }) } }),
      "POST /api/sops/s1/suggest/": () => ({ status: 201, body: { id: "x" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopScreen me={aMe({ role: "ECC" })} />, sopRoute);
    expect(await screen.findByText("Count the cartons.")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Lift with your legs.");
    expect(screen.getByRole("img", { name: "carton.jpg" })).toHaveAttribute("src", "/api/sops/s1/attachments/a1/");
    expect(screen.getByRole("img", { name: "Process map of Receiving an order" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Read and understood" }));
    expect(await screen.findByText(/Read and understood on November 3, 2026, version 1/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read and understood" })).not.toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "Suggest a change" }), "We weigh the cartons too.");
    await user.click(screen.getByRole("button", { name: "Send the suggestion" }));
    expect(await screen.findByText(/The practice sees your suggestion/)).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.url.endsWith("/suggest/"))?.body).toEqual({ text: "We weigh the cartons too." });
  });

  it("a version 2 that asks again shows what changed and the button again", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/sops/s1/": portal({ version: 2,
      change_note: "The scale replaces counting.", read: false, read_version: 1, read_at: "2026-11-02T10:00:00Z" }) }));
    renderRoute(<SopScreen me={aMe({ role: "ECC" })} />, sopRoute);
    expect(await screen.findByText(/The scale replaces counting./)).toBeInTheDocument();
    expect(screen.getByText(/Please read it again/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Read and understood" })).toBeInTheDocument();
  });

  it("the client owner sees who has read it, and can remind", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/sops/s1/": portal({ asked: false, reads: READS,
      may: { drafts: false, publishes: false, sees_reads: true, reminds: true, is_client: true } }) }));
    renderRoute(<SopScreen me={aMe({ role: "FCC" })} />, sopRoute);
    const panel = await screen.findByRole("region", { name: "Who has read it" });
    expect(within(panel).getByText("7 of 12 read")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: "Remind the 2 who haven't read it" })).toBeInTheDocument();
    expect(within(panel).queryByRole("link", { name: "Open the Sending queue" })).not.toBeInTheDocument();
  });

  it("the portal list says what is read and what is to read", async () => {
    // The list carries each person's own state: no call per SOP.
    vi.stubGlobal("fetch", mockApi({
      "GET /api/sops/": { may_create: false, sops: [
        row({ reads: null, mine: { asked: true, read: true, read_at: "2026-11-03T10:00:00Z" } }),
        row({ id: "s4", title: "Quoting a job", reads: null,
          mine: { asked: true, read: false, read_at: null } })] } }));
    renderRoute(<SopsScreen me={aMe({ role: "ECC" })} />);
    expect(await screen.findByText(/Read ✓ November 3, 2026/)).toBeInTheDocument();
    expect(await screen.findByText("To read")).toBeInTheDocument();
  });

  it("the company card: its SOPs, a brainstorm, and the Notebook pack built and downloaded", async () => {
    const user = userEvent.setup();
    const base = mockApi({
      "GET /api/sops/pack/": { runs: [{ id: "r1", name: "Order to shipment", tool: "Bottleneck finder", date: "2026-11-02" }],
        documents: [{ id: "d1", title: "Engagement letter", state: "Signed" }],
        always: ["Goals outline", "Plan by horizon", "Scorecard", "SOPs", "Strategy maps", "Meeting summaries"],
        never: "Mail, notes (PIN-locked or not) and People data are never in a pack.",
        prompts: [{ title: "Find the handoffs and bottlenecks", prompt: "Across these sources…" }],
        may_edit_prompts: true },
      "PUT /api/sops/pack/prompts/": { prompts: [{ title: "Handoffs", prompt: "Find them." }] },
      "GET /api/sops/": { may_create: true, sops: [row()] },
    });
    let packBody: unknown = null;
    const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url === "/api/sops/pack/" && init?.method === "POST") {
        packBody = JSON.parse(String(init.body));
        return { ok: true, status: 200, blob: async () => new Blob(["zip"]) } as unknown as Response;
      }
      return base(input, init);
    });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:pack", revokeObjectURL: () => undefined }));
    const clicked = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => undefined);
    renderRoute(<CompanySopsCard me={aMe({ role: "FF" })} companyId="c1" isClient />);
    expect(await screen.findByText("Receiving an order")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Notebook pack" }));
    const dialog = screen.getByRole("dialog", { name: "Notebook pack" });
    expect(await within(dialog).findByText(/never in a pack/)).toBeInTheDocument();
    await user.click(within(dialog).getByRole("checkbox", { name: /Order to shipment/ }));
    await user.click(within(dialog).getByRole("checkbox", { name: /Engagement letter/ }));
    await user.click(within(dialog).getByRole("button", { name: "Edit the prompts" }));
    expect(within(dialog).getByLabelText("Prompt 1 title")).toHaveValue("Find the handoffs and bottlenecks");
    await user.click(within(dialog).getByRole("button", { name: "Cancel" }));
    await user.click(within(dialog).getByRole("button", { name: "Build the pack" }));
    expect(await within(dialog).findByText(/The pack is downloaded/)).toBeInTheDocument();
    expect(packBody).toEqual({ company: "c1", runs: ["r1"], documents: ["d1"] });
    expect(clicked).toHaveBeenCalled();
    clicked.mockRestore();
  });

  it("an associate on a company page has no Notebook pack for an assistant", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/sops/": { may_create: true, sops: [] } }));
    renderRoute(<CompanySopsCard me={aMe({ role: "VA" })} companyId="c1" isClient />);
    expect(await screen.findByText("No SOPs for this company yet.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Notebook pack" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Brainstorm a process" })).toBeInTheDocument();
  });

  it("a KPI's Details lists the SOPs for this number, and nothing when there are none", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/sops/?kpi=k1": { may_create: false, sops: [row()] },
      "GET /api/sops/?kpi=k2": { may_create: false, sops: [] } }));
    const { container } = renderRoute(<><SopsForKpi kpiId="k1" /><SopsForKpi kpiId="k2" /></>);
    const group = await screen.findByRole("group", { name: "SOPs for this number" });
    expect(within(group).getByRole("link", { name: "Receiving an order" })).toHaveAttribute("href", "/sops/s1");
    expect(container.querySelectorAll(".sc-back-sops")).toHaveLength(1);
  });

  it("a note: Draft an SOP from this opens a brainstorm with the note", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "/api/notes/settings/": { audio_retention_days: 30, max_recording_seconds: 7200, warn_at_seconds: 6600 },
      "/api/tasks/": [], "/api/ai/actions/": { actions: [] },
      [`/api/notes/${NOTE_ID}/`]: aNote({ title: "Receiving walk-through", title_is_auto: false }),
      "POST /api/sops/brainstorms/": () => ({ status: 201, body: { id: "b1" } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<NoteDetail me={aMe({ role: "FF", has_plan: true })} />, { path: "/notes/:id", route: `/notes/${NOTE_ID}` });
    await user.click(await screen.findByRole("button", { name: "Draft an SOP from this" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url === "/api/sops/brainstorms/")?.body)
      .toEqual({ note: NOTE_ID }));
  });

  it("a locked note offers no SOP draft", async () => {
    vi.stubGlobal("fetch", mockApi({
      "/api/notes/settings/": { audio_retention_days: 30, max_recording_seconds: 7200, warn_at_seconds: 6600 },
      "/api/tasks/": [], "/api/ai/actions/": { actions: [] },
      [`/api/notes/${NOTE_ID}/`]: aNote({ title: "HR", title_is_auto: false, is_locked: true, unlocked: true }),
    }));
    renderRoute(<NoteDetail me={aMe({ role: "FF", has_plan: true })} />, { path: "/notes/:id", route: `/notes/${NOTE_ID}` });
    expect(await screen.findByText("Unlocked in this browser")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Draft an SOP from this" })).not.toBeInTheDocument();
  });
});
