import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Brainstorm, DEFAULT_LAYOUT, MediaStatus, SopFull, SopPortal } from "../lib/sops";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { SopScreen } from "./Sops";

/** The SOP's eleven sections, the brain dump and training material (2026-11-14). */

const ACME = { id: "c1", name: "Acme Fasteners", is_practice: false };
const sopRoute = { path: "/sops/:id", route: "/sops/s1" };

function full(over: Partial<SopFull> = {}): SopFull {
  return {
    id: "s1", title: "Receiving an order", status: "draft", category: "Shipping", version: 0,
    company: ACME, owner: "", review_date: null, published_at: null,
    updated_at: "2026-11-14T10:00:00Z", from_ai_app: false, reads: null,
    layout: DEFAULT_LAYOUT, number: "SHP-01", number_by_hand: false, effective_date: null,
    review_months: null, review_label: "", definitions: [], related: [], training: "",
    metrics: "", training_assets: [], revisions: [], brain_dump: null,
    purpose: "", applies_when: "", roles: [], steps: [{ text: "Count the cartons.", role: "", warning: "", images: [] }],
    sections: [], process_map: "", map_svg: null, owner_id: null, audience: "company",
    teams: [], people: [], kpis: [], attachments: [], versions: [], unpublished_changes: true,
    comments: [], brainstorms: [],
    may: { drafts: true, publishes: true, sees_reads: true, reminds: true, is_client: false,
      publish: true, edit: true },
    hints: {}, last_version: 0,
    choices: { owners: [], teams: [], people: [], kpis: [{ id: "k1", name: "On-time shipments" }],
      documents: [{ id: "d1", title: "Dock checklist", state: "Signed" }],
      sops: [{ id: "s2", title: "Cycle count", number: "SHP-02" }] },
    ...over,
  };
}

const MEDIA_OFF = { set: false, last4: "", verified_at: null, model: "gemini-2.5-flash",
  input_usd_per_mtok: "1.00", output_usd_per_mtok: "2.50", about_per_minute: { audio: "0.03", video: "0.04" },
  limits: { audio: { minutes: 60, mb: 50 }, video: { minutes: 15, mb: 100 } }, refused: "", notice: "" } as MediaStatus;

function storm(over: Partial<Brainstorm> = {}): Brainstorm {
  return { id: "b1", title: "Receiving an order", tier: "standard", company: ACME,
    sop: { id: "s1", title: "Receiving an order", status: "draft" }, sources: [], messages: [],
    proposals: [], spent_usd: "0", price: { kind: "chat", estimate_usd: "0.01", tier: "standard",
      model: "claude-sonnet-5-5", images: 0 }, refused: "", media: MEDIA_OFF,
    homes: { goals: [], projects: [] }, updated_at: "2026-11-14T10:00:00Z", ...over };
}

describe("the SOP's eleven sections (2026-11-14)", () => {
  beforeEach(() => { vi.unstubAllGlobals(); });

  it("shows the sections in the practice's order and names, and saves the new ones", async () => {
    const user = userEvent.setup();
    let saved: Record<string, unknown> = {};
    const layout = DEFAULT_LAYOUT.map((s) => s.key === "purpose" ? { ...s, title: "Why we do this" } : s);
    // The practice moved Procedure steps up, before Scope.
    const steps = layout.find((s) => s.key === "steps")!;
    const ordered = [layout[0], layout[1], steps, ...layout.slice(2).filter((s) => s.key !== "steps")];
    const fetchMock = mockApi({
      "GET /api/sops/s1/": full({ layout: ordered }),
      "PATCH /api/sops/s1/": (body: unknown) => { saved = body as Record<string, unknown>; return { body: full({ layout: ordered }) }; },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopScreen me={aMe({ role: "FF" })} />, sopRoute);
    await screen.findByRole("heading", { name: "Why we do this" });
    const titles = screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent);
    const at = (t: string) => titles.indexOf(t);
    expect(at("Overview")).toBeLessThan(at("Why we do this"));
    expect(at("Procedure steps")).toBeLessThan(at("Scope"));
    expect(at("Performance metrics and monitoring")).toBeLessThan(at("Revision history"));
    await user.clear(screen.getByLabelText("SOP number"));
    await user.type(screen.getByLabelText("SOP number"), "shp-9");
    await user.selectOptions(screen.getByLabelText("Review frequency"), "custom");
    const months = screen.getByLabelText("Review every how many months");
    await user.clear(months);
    await user.type(months, "18");
    await user.click(screen.getByRole("button", { name: "Add a term" }));
    await user.type(screen.getByLabelText("Term 1"), "PO");
    await user.type(screen.getByLabelText("Definition 1"), "Purchase order");
    await user.type(screen.getByLabelText("Trigger or if/then for step 1"), "When the truck is in");
    await user.click(screen.getByRole("button", { name: "Add a related item" }));
    await user.selectOptions(screen.getByLabelText("Kind of related item 1"), "sop");
    await user.selectOptions(screen.getByLabelText("SOP for related item 1"), "s2");
    await user.type(screen.getByLabelText("Training requirements"), "Two supervised deliveries.");
    await user.click(screen.getAllByRole("button", { name: "Save" })[0]);
    await waitFor(() => expect(saved.number).toBe("SHP-9"));
    expect(saved.review_months).toBe(18);
    expect(saved.definitions).toEqual([{ term: "PO", definition: "Purchase order" }]);
    expect((saved.steps as { when: string }[])[0].when).toBe("When the truck is in");
    expect(saved.related).toEqual([{ kind: "sop", ref: "s2", title: "Cycle count", url: "" }]);
    expect(saved.training).toBe("Two supervised deliveries.");
  });

  it("the brain dump is priced first, fills a draft, and the accepted draft shows at once", async () => {
    const user = userEvent.setup();
    let accepted = false;
    const draft = { id: "p1", kind: "draft" as const, label: "The SOP", state: "proposed" as const,
      payload: { title: "Receiving an order", purpose: "Every delivery checked the day it lands.",
        applies_when: "", roles: [], steps: [{ text: "Count the cartons.", role: "", warning: "" }], category: "" },
      why: "From your notes.", result: {}, decided_by: "", cost_usd: "0.05",
      diff: { fields: { purpose: { from: "", to: "Every delivery checked the day it lands." } }, steps: [] } };
    const fetchMock = mockApi({
      "GET /api/sops/s1/": () => ({ body: accepted
        ? full({ purpose: "Every delivery checked the day it lands.", updated_at: "2026-11-14T11:00:00Z", brain_dump: "b1" })
        : full() }),
      "GET /api/sops/brainstorms/b1/": storm({ proposals: [] }),
      "POST /api/sops/s1/brain-dump/price/": { kind: "draft", estimate_usd: "0.0512", tier: "standard",
        model: "claude-sonnet-5-5", images: 0, refused: "", brainstorm: "b1" },
      "POST /api/sops/s1/brain-dump/fill/": storm({ proposals: [draft] }),
      "POST /api/sops/brainstorms/b1/proposals/p1/accept/": () => {
        accepted = true;
        return { body: storm({ proposals: [{ ...draft, state: "accepted",
          landed: { text: "Drafted into the SOP “Receiving an order”.", href: "/sops/s1", link: "Open the SOP" } }] }) };
      },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopScreen me={aMe({ role: "FF" })} />, sopRoute);
    const box = await screen.findByRole("region", { name: "Brain dump" });
    const fill = within(box).getByRole("button", { name: "Fill the SOP from this" });
    expect(fill).toBeDisabled();
    await user.type(within(box).getByLabelText("Brain dump"), "Trucks come at 7. We count cartons.");
    expect(await within(box).findByText(/Costs about \$0\.05/)).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.url.endsWith("/brain-dump/fill/"))).toBe(false);
    await user.click(within(box).getByRole("button", { name: "Fill the SOP from this" }));
    const proposal = await screen.findByRole("region", { name: "The SOP proposed" });
    expect(fetchMock.calls.find((c) => c.url.endsWith("/brain-dump/fill/"))?.body)
      .toEqual({ text: "Trucks come at 7. We count cartons." });
    await user.click(within(proposal).getByRole("button", { name: "Accept" }));
    // The page refetches, and the editor holds the new working copy.
    await waitFor(() => expect(screen.getByLabelText("Purpose")).toHaveValue("Every delivery checked the day it lands."));
  });

  it("training material: a link added, the SOP's Notebook pack, and what the notebook made", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/sops/s1/": full(),
      "POST /api/sops/s1/training/": { training_assets: [{ id: "t1", kind: "video", label: "Video",
        title: "Walkthrough", url: "https://drive.google.com/file/d/x/view", is_link: true, size: null }] },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopScreen me={aMe({ role: "FF" })} />, sopRoute);
    const area = await screen.findByRole("region", { name: "Training material" });
    expect(within(area).getByRole("link", { name: "Notebook pack for this SOP" }))
      .toHaveAttribute("href", "/api/sops/s1/pack/");
    await user.click(within(area).getByRole("button", { name: "Add what the notebook made" }));
    expect(within(area).getByText(/Choose what the\s+notebook made/)).toBeInTheDocument();
    await user.selectOptions(within(area).getByLabelText("Kind of training material"), "video");
    await user.type(within(area).getByLabelText("Title of the training material"), "Walkthrough");
    await user.click(within(area).getByRole("radio", { name: "A link" }));
    await user.type(within(area).getByLabelText("Link to the training material"), "https://drive.google.com/file/d/x/view");
    await user.click(within(area).getByRole("button", { name: "Add it" }));
    expect(await within(area).findByRole("link", { name: "Walkthrough" }))
      .toHaveAttribute("href", "https://drive.google.com/file/d/x/view");
    expect(fetchMock.calls.some((c) => c.method === "POST" && c.url === "/api/sops/s1/training/")).toBe(true);
  });

  it("an assistant has no Notebook pack; a published SOP has no brain dump", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/sops/s1/": full({ status: "published", version: 1,
      may: { drafts: true, publishes: false, sees_reads: true, reminds: false, is_client: false, publish: false, edit: true } }) }));
    renderRoute(<SopScreen me={aMe({ role: "VA" })} />, sopRoute);
    const area = await screen.findByRole("region", { name: "Training material" });
    expect(within(area).queryByRole("link", { name: "Notebook pack for this SOP" })).not.toBeInTheDocument();
    expect(screen.queryByRole("region", { name: "Brain dump" })).not.toBeInTheDocument();
  });

  it("the portal reads the sections in order, with training material and the revision history", async () => {
    const reader: SopPortal = {
      id: "s1", title: "Receiving an order", version: 2, published_at: "2026-11-10T10:00:00Z",
      change_note: "Added the scale.", minor: false, layout: DEFAULT_LAYOUT, number: "SHP-01",
      effective_date: "2026-11-01", review_months: 6, review_label: "Twice a year",
      purpose: "Every order checked in.", applies_when: "Every delivery.",
      definitions: [{ term: "PO", definition: "Purchase order" }],
      roles: [{ name: "Receiver", does: "Checks it" }],
      steps: [{ text: "Count the cartons.", role: "Receiver", when: "When the truck is in", warning: "", images: [] }],
      related: [{ kind: "sop", title: "Cycle count", ref: "s2", number: "SHP-02", href: "/sops/s2" }],
      training: "Two supervised deliveries.",
      training_assets: [{ id: "t1", kind: "quiz", label: "Quiz", title: "Receiving quiz", url: "/api/sops/s1/training/t1/", is_link: false, size: 2000 }],
      metrics: "Deliveries checked the same day.", sections: [], owner: "Marvin Martian",
      category: "Shipping", review_date: "2027-05-10", kpis: [{ id: "k1", name: "On-time shipments" }],
      map_svg: null, attachments: [],
      revisions: [{ date: "2026-11-01", version: 1, change: "First version.", author: "John Carter" },
        { date: "2026-11-10", version: 2, change: "Added the scale.", author: "John Carter" }],
      asked: true, read: false, read_at: null, read_version: null, read_by: "2026-11-17",
      may: { drafts: false, publishes: false, sees_reads: false, reminds: false, is_client: true },
    };
    vi.stubGlobal("fetch", mockApi({ "GET /api/sops/s1/": reader }));
    renderRoute(<SopScreen me={aMe({ role: "ECC" })} />, sopRoute);
    await screen.findByRole("region", { name: "Overview" });
    const names = screen.getAllByRole("region").map((r) => r.getAttribute("aria-label"));
    const order = ["Overview", "Purpose", "Scope", "Definitions and acronyms", "Roles and responsibilities",
      "Procedure steps", "Related documents and resources", "Training requirements",
      "Performance metrics and monitoring", "Revision history"];
    expect(names.filter((n) => order.includes(n ?? ""))).toEqual(order);   // no flowchart: none drawn
    expect(screen.getByText("Twice a year")).toBeInTheDocument();
    expect(screen.getByText("When the truck is in")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Receiving quiz" })).toHaveAttribute("href", "/api/sops/s1/training/t1/");
    expect(screen.getByRole("link", { name: "Cycle count" })).toHaveAttribute("href", "/sops/s2");
    const history = screen.getByRole("region", { name: "Revision history" });
    expect(within(history).getAllByRole("row")).toHaveLength(3);
  });
});
