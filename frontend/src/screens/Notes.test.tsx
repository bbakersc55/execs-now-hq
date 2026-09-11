import { fireEvent, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NoteCapture } from "../components/NoteCapture";
import { NOTE_ID, SECRET, aMe, aNote, aStub } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { NoteDetail } from "./NoteDetail";

const SETTINGS = { audio_retention_days: 30, max_recording_seconds: 7200, warn_at_seconds: 6600 };

function showNote(note: unknown, extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "/api/notes/settings/": SETTINGS,
    "/api/tasks/": [],
    ...extra,
    [`/api/notes/${NOTE_ID}/`]: note,
  });
  vi.stubGlobal("fetch", fetchMock);
  const view = renderRoute(<NoteDetail me={aMe()} />, { path: "/notes/:id", route: `/notes/${NOTE_ID}` });
  return { fetchMock, ...view };
}

describe("AC-2.3 in the UI — the title leak", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("will not set a PIN on an auto-titled note until a real title is typed, and says why", async () => {
    const user = userEvent.setup();
    const order: string[] = [];
    const { fetchMock } = showNote(aNote(), {
      [`PATCH /api/notes/${NOTE_ID}/`]: (body: unknown) => { order.push("patch"); return { body: { ...aNote(), ...(body as object) } }; },
      [`POST /api/notes/${NOTE_ID}/pin/`]: () => { order.push("pin"); return { body: aNote({ title: "HR matter", title_is_auto: false, is_locked: true, unlocked: true }) }; },
    });

    await user.click(await screen.findByRole("button", { name: "Set a PIN" }));
    const dialog = screen.getByRole("dialog", { name: "Set a PIN" });
    expect(dialog).toHaveTextContent("Type a title first");
    expect(dialog).toHaveTextContent("A locked note still shows its title");
    expect(screen.getByLabelText("PIN")).toBeDisabled();
    expect(screen.getByRole("button", { name: "Set PIN" })).toBeDisabled();

    // Retyping the derived title is not a real title.
    await user.type(screen.getByLabelText("Title shown on the locked note"), SECRET);
    expect(screen.getByLabelText("PIN")).toBeDisabled();

    await user.clear(screen.getByLabelText("Title shown on the locked note"));
    await user.type(screen.getByLabelText("Title shown on the locked note"), "HR matter");
    await user.type(screen.getByLabelText("PIN"), "4821");
    await user.type(screen.getByLabelText("Confirm PIN"), "4821");
    await user.click(screen.getByRole("button", { name: "Set PIN" }));

    await waitFor(() => expect(order).toEqual(["patch", "pin"]));
    const patch = fetchMock.calls.find((c) => c.method === "PATCH");
    expect(patch?.body).toEqual({ title: "HR matter" });
  });

  it("does not ask for a title when the note already has one of its own", async () => {
    const user = userEvent.setup();
    showNote(aNote({ title: "HR matter", title_is_auto: false }));
    await user.click(await screen.findByRole("button", { name: "Set a PIN" }));
    expect(screen.queryByText(/Type a title first/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("PIN")).toBeEnabled();
  });

  it("states what a PIN does not protect against (FR-2.13)", async () => {
    const user = userEvent.setup();
    showNote(aNote({ title: "HR matter", title_is_auto: false }));
    await user.click(await screen.findByRole("button", { name: "Set a PIN" }));
    expect(screen.getByRole("dialog")).toHaveTextContent(
      /not encryption.*founder fractional.*database export.*nightly backup/s,
    );
  });
});

describe("a locked note renders as its stub", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the title, an unlock form, and nothing else", async () => {
    const { container } = showNote(aStub());
    expect(await screen.findByRole("heading", { name: /HR matter/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Unlock" })).toBeInTheDocument();
    expect(container.innerHTML).not.toContain(SECRET);
    expect(screen.queryByText(/Email me a link/)).not.toBeInTheDocument();
  });

  it("offers the FF the reset, which says it clears rather than reveals", async () => {
    showNote(aStub({ can_reset_pin: true }));
    expect(await screen.findByRole("button", { name: "Email me a link that clears it" })).toBeInTheDocument();
    expect(screen.getByText(/never shows what the PIN was/)).toBeInTheDocument();
  });

  it("shows the server's lockout message after too many wrong PINs", async () => {
    const user = userEvent.setup();
    showNote(aStub(), {
      [`POST /api/notes/${NOTE_ID}/unlock/`]: () => ({
        status: 423, body: { detail: "Too many wrong PINs. This note is locked for 15 minutes." },
      }),
    });
    await user.type(await screen.findByLabelText("PIN"), "0000");
    await user.click(screen.getByRole("button", { name: "Unlock" }));
    expect(await screen.findByText(/locked for 15 minutes/)).toBeInTheDocument();
  });
});

describe("AC-2.7 in the UI — the summary is proposed", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const recorded = aNote({
    title: "Recording, Sep 11, 9:00 AM", body: "", source: "recording", has_audio: true,
    audio_duration_seconds: 60, transcription_state: "done",
    transcript: "We agreed to move the warehouse in March.",
    summary_state: "proposed", proposed_summary: "**Summary** — Warehouse moves in March.",
  });

  it("shows the draft beside the transcript, labelled as not attached", async () => {
    showNote(recorded);
    expect(await screen.findByText(/not attached until you accept it/)).toBeInTheDocument();
    expect(screen.getByText("We agreed to move the warehouse in March.")).toBeInTheDocument();
    for (const name of ["Accept", "Edit summary", "Discard"]) {
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
    }
  });

  it("sends an edited summary as the accepted text", async () => {
    const user = userEvent.setup();
    const { fetchMock } = showNote(recorded, {
      [`POST /api/notes/${NOTE_ID}/summary/accept/`]: aNote({ ...recorded, summary_state: "accepted", summary: "Edited." }),
    });
    await user.click(await screen.findByRole("button", { name: "Edit summary" }));
    await user.clear(screen.getByLabelText("Edit summary"));
    await user.type(screen.getByLabelText("Edit summary"), "Edited.");
    await user.click(screen.getByRole("button", { name: "Accept edited summary" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.url.endsWith("/summary/accept/"))).toBe(true));
    expect(fetchMock.calls.find((c) => c.url.endsWith("/summary/accept/"))?.body).toEqual({ text: "Edited." });
  });

  it("tells a non-author the author reviews it", async () => {
    showNote({ ...recorded, can_review_summary: false });
    expect(await screen.findByText(/Waiting for the note's author/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept" })).not.toBeInTheDocument();
  });

  it("explains 'no speech detected' and keeps the audio for retry", async () => {
    showNote(aNote({ source: "recording", has_audio: true, transcription_state: "failed",
      transcription_error: "No speech detected.", no_speech: true }));
    expect(await screen.findByText("No speech detected.")).toBeInTheDocument();
    expect(screen.getByText(/permission to use the microphone/)).toBeInTheDocument();
    expect(screen.getByText(/headphones/)).toBeInTheDocument();
    expect(screen.getByText(/was not muted/)).toBeInTheDocument();
    expect(screen.getByText(/The audio is kept/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry transcription" })).toBeInTheDocument();
  });

  it("flags audio kept past retention because it never transcribed", async () => {
    showNote(aNote({ source: "recording", has_audio: true, transcription_state: "failed",
      transcription_error: "no speech", retention_overdue: true }));
    expect(await screen.findByText(/only record of the call/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Retry transcription" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Discard audio" })).toBeInTheDocument();
  });
});

describe("AC-2.1 / AC-2.2 — capture", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function capture() {
    const fetchMock = mockApi({
      "/api/tasks/": [{ id: "t1", title: "Lease review", description: "", status: "not_started",
                        due_date: null, owner: null, contact: null }],
      "/api/companies/": [{ id: "co1", name: "Acme" }],
      "POST /api/notes/": (body: unknown) => ({ status: 201, body: aNote({ id: "new", ...(body as object) }) }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<NoteCapture />);
    return fetchMock;
  }

  it("opens on 'n' from anywhere and saves with only a body", async () => {
    const user = userEvent.setup();
    const fetchMock = capture();
    fireEvent.keyDown(window, { key: "n" });
    const body = await screen.findByLabelText("Note");
    await waitFor(() => expect(body).toHaveFocus());
    await user.type(body, "Lease renews in March");  // an 'n' typed here stays text
    await user.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(screen.getByText("Note saved.")).toBeInTheDocument());
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toMatchObject({
      body: "Lease renews in March", contact: null, company: null, task: null,
    });
  });

  it("labels each choice beside its own radio, and the search field as a contact search", async () => {
    const user = userEvent.setup();
    capture();
    await user.click(screen.getByRole("button", { name: /New note/ }));
    for (const name of ["Nothing", "A contact", "A company"]) {
      const radio = screen.getByRole("radio", { name });
      expect(radio.closest("label")).toHaveTextContent(name);  // the label wraps its own button
    }
    expect(screen.queryByLabelText("Find a contact by name")).not.toBeInTheDocument();
    await user.click(screen.getByRole("radio", { name: "A contact" }));
    expect(screen.getByLabelText("Find a contact by name")).toBeInTheDocument();
    expect(screen.queryByLabelText("Company")).not.toBeInTheDocument();
  });

  it("offers no way to link a contact and a company at once", async () => {
    const user = userEvent.setup();
    const fetchMock = capture();
    await user.click(screen.getByRole("button", { name: /New note/ }));
    const group = screen.getByRole("radiogroup", { name: /contact or a company/ });
    expect(group.querySelectorAll('input[type="radio"]')).toHaveLength(3);

    await user.click(screen.getByLabelText("A company"));
    await user.selectOptions(await screen.findByLabelText("Company"), "co1");
    await user.click(screen.getByLabelText("A contact"));  // switching clears the company
    await user.selectOptions(screen.getByLabelText(/^Task/), "t1");
    await user.type(screen.getByLabelText("Note"), "x");
    await user.click(screen.getByRole("button", { name: "Save note" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(true));
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toMatchObject({
      company: null, contact: null, task: "t1",
    });
  });
});
