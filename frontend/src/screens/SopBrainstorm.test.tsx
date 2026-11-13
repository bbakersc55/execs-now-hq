import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { Brainstorm, MediaStatus, Proposal } from "../lib/sops";
import { mockApi, renderRoute } from "../test/render";
import { SopBrainstormScreen } from "./SopBrainstorm";

const MEDIA_OFF: MediaStatus = { set: false, last4: "", verified_at: null, model: "gemini-2.5-flash",
  input_usd_per_mtok: "1.00", output_usd_per_mtok: "2.50",
  about_per_minute: { audio: "0.03", video: "0.04" },
  limits: { audio: { minutes: 60, mb: 50 }, video: { minutes: 15, mb: 100 } },
  refused: "Video and audio are read with a media key (Gemini), and none is set. The practice owner adds one under AI usage; or paste a transcript as text instead.",
  notice: "Video and audio files are sent to Google to be read, under the practice's own agreement with Google. Nothing else is." };

function aBrainstorm(over: Partial<Brainstorm> = {}): Brainstorm {
  return { id: "b1", title: "Receiving an order", tier: "standard",
    company: { id: "c1", name: "Acme Fasteners", is_practice: false },
    sop: { id: "s1", title: "Receiving an order", status: "draft" },
    sources: [{ id: "src1", kind: "note", label: "A note", title: "Note: Dock walk", state: "ready",
      error: "", chars: 400, seconds: null, kept: false, preview: "Trucks arrive at 7." }],
    messages: [{ id: "m1", role: "claude", text: "Who checks the cartons?", by: "", at: "2026-11-12T10:00:00Z",
      cost_usd: "0.0210" }],
    proposals: [], spent_usd: "0.0210",
    price: { kind: "chat", estimate_usd: "0.0300", tier: "standard", model: "claude-sonnet-5-5", images: 0 },
    refused: "", media: MEDIA_OFF,
    homes: { goals: [{ id: "g1", name: "Ship on time" }], projects: [{ id: "p1", name: "Dock reset", goal: "g1" }] },
    updated_at: "2026-11-12T10:00:00Z", ...over };
}

const DRAFT: Proposal = { id: "p-draft", kind: "draft", label: "The SOP", state: "proposed",
  payload: { title: "Receiving an order", purpose: "Check every order in.", applies_when: "",
    roles: [], steps: [{ text: "Count the cartons.", role: "", warning: "" },
      { text: "Weigh the cartons.", role: "", warning: "" }], category: "" },
  why: "From the dock walk note.", result: {}, decided_by: "", cost_usd: "0.0800",
  diff: { fields: { purpose: { from: "Every order checked.", to: "Check every order in." } },
    steps: [{ change: "same", text: "Count the cartons." }, { change: "removed", text: "Sign it." },
      { change: "added", text: "Weigh the cartons." }] } };

const CHECKLIST: Proposal = { id: "p-check", kind: "checklist", label: "A checklist", state: "proposed",
  payload: { tasks: [{ title: "Train the dock team", due_in_days: 7 }, { title: "Print the check sheet", due_in_days: null }] },
  why: "", result: {}, decided_by: "", cost_usd: "0.0300" };

const route = { path: "/sop-brainstorms/:id", route: "/sop-brainstorms/b1" };
const prices = (body: unknown) => {
  const { kind, message } = body as { kind: string; message: string };
  const usd = { chat: message ? "0.0400" : "0.0300", draft: "0.0800", map: "0.0500", checklist: "0.0600", measures: "0.0200" }[kind];
  return { body: { kind, estimate_usd: usd, tier: "standard", model: "claude-sonnet-5-5", images: 0, refused: "", spent_usd: "0.021" } };
};

describe("SOP brainstorm (P10)", () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => vi.restoreAllMocks());

  it("shows the price before a send, and before each of the four actions", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/sops/brainstorms/b1/": aBrainstorm(),
      "POST /api/sops/brainstorms/b1/price/": prices,
      "POST /api/sops/brainstorms/b1/send/": () => ({ status: 201, body: aBrainstorm({ messages: [
        ...aBrainstorm().messages, { id: "m2", role: "user", text: "The receiver.", by: "Bryan Baker", at: "", cost_usd: null },
        { id: "m3", role: "claude", text: "Got it.", by: "", at: "", cost_usd: "0.0300" }], spent_usd: "0.0510",
        updated_at: "2026-11-12T10:05:00Z" }) }),
      "POST /api/sops/brainstorms/b1/act/draft/": () => ({ status: 201, body: aBrainstorm({ proposals: [DRAFT] }) }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopBrainstormScreen />, route);
    expect(await screen.findByRole("button", { name: "Send (about $0.03)" })).toBeDisabled();
    expect(screen.getByLabelText("Spent so far")).toHaveTextContent("Spent so far $0.02");
    const actions = screen.getByRole("region", { name: "Ask Claude to" });
    expect(await within(actions).findByRole("button", { name: "Draft the SOP (about $0.08)" })).toBeEnabled();
    expect(within(actions).getByRole("button", { name: "Draw the process map (about $0.05)" })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Make the checklist (about $0.06)" })).toBeInTheDocument();
    expect(within(actions).getByRole("button", { name: "Suggest measures (about $0.02)" })).toBeInTheDocument();
    await user.type(screen.getByLabelText("Your message"), "The receiver.");
    expect(await screen.findByRole("button", { name: "Send (about $0.04)" }, { timeout: 2000 })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Send (about $0.04)" }));
    expect(await screen.findByText("Got it.")).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.url.endsWith("/send/"))?.body).toEqual({ text: "The receiver." });
    await user.click(within(actions).getByRole("button", { name: /Draft the SOP/ }));
    expect(await screen.findByRole("region", { name: "The SOP proposed" })).toBeInTheDocument();
  });

  it("a draft that changes the SOP shows as a diff; Accept applies it, Discard drops it", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/sops/brainstorms/b1/": aBrainstorm({ proposals: [DRAFT, { ...CHECKLIST, id: "p2" }] }),
      "POST /api/sops/brainstorms/b1/price/": prices,
      "POST /api/sops/brainstorms/b1/proposals/p-draft/accept/": () => ({ body: aBrainstorm({ proposals: [
        { ...DRAFT, state: "accepted", decided_by: "Bryan Baker" }, { ...CHECKLIST, id: "p2" }] }) }),
      "POST /api/sops/brainstorms/b1/proposals/p2/discard/": () => ({ body: aBrainstorm({ proposals: [
        { ...DRAFT, state: "accepted", decided_by: "Bryan Baker" }, { ...CHECKLIST, id: "p2", state: "discarded" }] }) }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopBrainstormScreen />, route);
    const card = await screen.findByRole("region", { name: "The SOP proposed" });
    const diff = within(card).getByLabelText("What would change");
    expect(within(diff).getByText("+ Weigh the cartons.")).toHaveClass("sop-add");
    expect(within(diff).getByText("− Sign it.")).toHaveClass("sop-del");
    expect(within(diff).getByText("+ Check every order in.")).toBeInTheDocument();
    await user.click(within(card).getByRole("button", { name: "Accept" }));
    expect(await screen.findByText("Accepted")).toBeInTheDocument();
    await user.click(within(screen.getByRole("region", { name: "A checklist proposed" })).getByRole("button", { name: "Discard" }));
    expect(await screen.findByText("Discarded")).toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.url.endsWith("/p2/discard/"))).toBe(true);
  });

  it("a draft can be edited before it is accepted", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/sops/brainstorms/b1/": aBrainstorm({ proposals: [{ ...DRAFT, diff: {} }] }),
      "POST /api/sops/brainstorms/b1/price/": prices,
      "POST /api/sops/brainstorms/b1/proposals/p-draft/accept/": () => ({ body: aBrainstorm() }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopBrainstormScreen />, route);
    const card = await screen.findByRole("region", { name: "The SOP proposed" });
    await user.click(within(card).getByRole("button", { name: "Edit" }));
    const second = within(card).getByLabelText("Proposed step 2");
    await user.clear(second);
    await user.type(second, "Weigh each carton.");
    await user.click(within(card).getByRole("button", { name: "Accept" }));
    await waitFor(() => expect((fetchMock.calls.find((c) => c.url.endsWith("/accept/"))?.body as
      { edits: { steps: { text: string }[] } }).edits.steps[1].text).toBe("Weigh each carton."));
  });

  it("a checklist is made under a chosen project, with the tasks ticked", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/sops/brainstorms/b1/": aBrainstorm({ proposals: [CHECKLIST] }),
      "POST /api/sops/brainstorms/b1/price/": prices,
      "POST /api/sops/brainstorms/b1/proposals/p-check/accept/": () => ({ body: aBrainstorm() }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopBrainstormScreen />, route);
    const card = await screen.findByRole("region", { name: "A checklist proposed" });
    const accept = within(card).getByRole("button", { name: "Accept" });
    expect(accept).toBeDisabled();
    await user.click(within(card).getByRole("checkbox", { name: "Make: Print the check sheet" }));
    await user.selectOptions(within(card).getByLabelText("Under which goal or project"), "project:p1");
    await user.click(accept);
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/accept/"))?.body)
      .toEqual({ edits: { chosen: [0], titles: {}, project: "p1" } }));
  });

  it("with no media key, video or audio says so and offers to paste a transcript", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/sops/brainstorms/b1/": aBrainstorm(),
      "POST /api/sops/brainstorms/b1/price/": prices,
      "POST /api/sops/brainstorms/b1/sources/": () => ({ status: 201, body: aBrainstorm() }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopBrainstormScreen />, route);
    await user.click(await screen.findByRole("button", { name: "Add video or audio" }));
    const dialog = screen.getByRole("dialog", { name: "Add video or audio" });
    expect(dialog).toHaveTextContent("none is set");
    await user.click(within(dialog).getByRole("button", { name: "Paste a transcript instead" }));
    const paste = screen.getByRole("dialog", { name: "Paste text" });
    expect(within(paste).getByLabelText("Source title")).toHaveValue("Transcript");
    await user.type(within(paste).getByLabelText("Text to add"), "Receiver: I count the cartons.");
    await user.click(within(paste).getByRole("button", { name: "Add the text" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.url.endsWith("/sources/"))?.body)
      .toEqual({ kind: "pasted", title: "Transcript", text: "Receiver: I count the cartons." }));
  });

  it("with a media key, a recording is priced from its length before it is sent", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/sops/brainstorms/b1/": aBrainstorm({ media: { ...MEDIA_OFF, set: true, refused: "" } }),
      "POST /api/sops/brainstorms/b1/price/": prices,
      "POST /api/sops/brainstorms/b1/media/": () => ({ status: 201, body: aBrainstorm({ sources: [] }) }) });
    vi.stubGlobal("fetch", fetchMock);
    vi.stubGlobal("URL", Object.assign(URL, { createObjectURL: () => "blob:x", revokeObjectURL: () => undefined }));
    const real = document.createElement.bind(document);
    vi.spyOn(document, "createElement").mockImplementation(((tag: string) => {
      if (tag !== "audio" && tag !== "video") return real(tag);
      const fake: Record<string, unknown> = { preload: "", duration: 180, onloadedmetadata: null, onerror: null };
      Object.defineProperty(fake, "src", { set() { setTimeout(() => (fake.onloadedmetadata as () => void)?.(), 0); } });
      return fake as unknown as HTMLElement;
    }) as typeof document.createElement);
    renderRoute(<SopBrainstormScreen />, route);
    await user.click(await screen.findByRole("button", { name: "Add video or audio" }));
    const dialog = screen.getByRole("dialog", { name: "Add video or audio" });
    expect(dialog).toHaveTextContent("Audio up to 60 minutes and 50 MB");
    expect(dialog).toHaveTextContent("sent to Google");
    expect(within(dialog).getByRole("checkbox", { name: /Keep the file/ })).not.toBeChecked();
    await user.upload(within(dialog).getByLabelText("Video or audio file"),
      new File(["x"], "walk.m4a", { type: "audio/mp4" }));
    expect(await within(dialog).findByText("3 minutes of audio: about $0.09 to read with Gemini.")).toBeInTheDocument();
    await user.click(within(dialog).getByRole("button", { name: "Read it (about $0.09)" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.endsWith("/media/") && c.method === "POST")).toBe(true));
  });

  it("switching to Deep is saved on the brainstorm", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/sops/brainstorms/b1/": aBrainstorm(),
      "POST /api/sops/brainstorms/b1/price/": prices,
      "PATCH /api/sops/brainstorms/b1/": (body: unknown) => ({ body: aBrainstorm({ tier: (body as { tier: "deep" }).tier }) }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<SopBrainstormScreen />, route);
    await user.click(await screen.findByRole("radio", { name: "Deep" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body).toEqual({ tier: "deep" }));
    expect(await screen.findByRole("radio", { name: "Deep" })).toBeChecked();
  });
});
