import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { SendingQueue } from "./SendingQueue";

const row = (key: string, category: string, subject: string, to: string,
             kind = "outbox") => ({
  key, kind, id: key.split(":")[1], category, label: kind === "digest" ? "Progress digest"
    : "Referral touch", to_name: to, to_address: `${to.toLowerCase()}@x.invalid`,
  from_address: "info@practice.invalid", subject, created_at: "2026-09-28T10:00:00Z",
  expires_at: "2026-10-05T10:00:00Z", sends: "when approved", warning: "",
  is_ai_generated: false, body_text: "Hi", body_html: "" });

const ROWS = [
  row("outbox:m1", "marketing", "Checking in", "Dana"),
  row("outbox:m2", "marketing", "Hello again", "Priya"),
  row("digest:d1", "updates", "Weekly update", "Tom", "digest"),
];

function show(me = aMe(), extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    "GET /api/sending-queue/preview/": { subject: "Checking in", from: "info@practice.invalid",
      to: "dana@x.invalid", html: "<p>Hi Dana</p>", text: "Hi Dana" },
    "GET /api/sending-queue/": ROWS,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<SendingQueue me={me} />);
  return fetchMock;
}

const posted = (fetchMock: ReturnType<typeof mockApi>, end: string) =>
  fetchMock.calls.filter((c) => c.method === "POST" && c.url.endsWith(end)).map((c) => c.body);

/** Owner, 2026-09-28 — one list, full preview, approve / edit / skip. */
describe("the sending queue", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("filters by category and approves everything selected in that view", async () => {
    const user = userEvent.setup();
    const fetchMock = show(aMe(), { "POST /api/sending-queue/approve/":
      { done_count: 2, failed: [] } });
    await user.click(await screen.findByRole("tab", { name: /Marketing/ }));
    expect(screen.queryByText("Weekly update")).not.toBeInTheDocument();
    await user.click(screen.getByLabelText("Select all in this view"));
    await user.click(screen.getByRole("button", { name: "Approve selected" }));

    await waitFor(() => expect(posted(fetchMock, "/approve/"))
      .toEqual([{ keys: ["outbox:m1", "outbox:m2"] }]));
    expect(await screen.findByText("2 approved.")).toBeInTheDocument();
  });

  it("filters by recipient", async () => {
    const user = userEvent.setup();
    show();
    await user.type(await screen.findByLabelText("Filter by recipient"), "tom");
    expect(screen.getByText("Weekly update")).toBeInTheDocument();
    expect(screen.queryByText("Checking in")).not.toBeInTheDocument();
  });

  it("shows the one chosen exactly as it lands, in a sandboxed frame", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("button", { name: /Checking in/ }));
    const frame = await screen.findByTitle("Exactly as it lands");
    await waitFor(() => expect(frame).toHaveAttribute("srcdoc", "<p>Hi Dana</p>"));
    expect(frame).toHaveAttribute("sandbox", "");
    await user.click(screen.getByRole("tab", { name: "Plain text" }));
    expect(screen.getByText("Hi Dana")).toBeInTheDocument();
  });

  it("edits a draft through the Outbox's own edit", async () => {
    const user = userEvent.setup();
    const fetchMock = show(aMe(), { "PATCH /api/outbox/m1/edit/": {} });
    await user.click(await screen.findByRole("button", { name: /Checking in/ }));
    await user.click(await screen.findByRole("button", { name: "Edit" }));
    const subject = screen.getByLabelText("Edit subject");
    await user.clear(subject);
    await user.type(subject, "Quick hello");
    await user.click(screen.getByRole("button", { name: "Save edit" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toMatchObject({ subject: "Quick hello" }));
  });

  it("offers a VA skip and edit but not approve", async () => {
    const user = userEvent.setup();
    show(aMe({ role: "VA" }));
    await user.click(await screen.findByRole("button", { name: /Checking in/ }));
    const detail = (await screen.findByTitle("Exactly as it lands")).closest("section")!;
    expect(within(detail).queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
    expect(within(detail).getByRole("button", { name: "Skip" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve selected" })).not.toBeInTheDocument();
  });
});
