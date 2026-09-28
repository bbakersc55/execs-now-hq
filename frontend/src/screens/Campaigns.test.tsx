import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Campaign } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { CampaignDetail } from "./Campaigns";

const CAMPAIGN: Campaign = {
  id: "k1", name: "Autumn note", subject: "Hello {FirstName}", sender: "alias",
  body_mode: "rich", body_html: "<p>Hi {FirstName}</p>", send_as_is: false,
  created_at: "2026-09-28T10:00:00Z", updated_at: "2026-09-28T10:00:00Z",
  created_by_name: "Bryan Baker",
  stats: { recipients: 0, queued: 0, sent: 0, unsubscribed: 0, not_sent: 0 },
};

const CANDIDATES = [
  { id: "c1", name: "Dana Reyes", email: "dana@x.invalid", company: "Acme", unsendable: "" },
  { id: "c2", name: "Priya Shah", email: "priya@x.invalid", company: "", unsendable: "" },
  { id: "c3", name: "Left Early", email: "left@x.invalid", company: "",
    unsendable: "unsubscribed from marketing emails" },
];

function show(extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    "POST /api/campaigns/k1/preview/": { subject: "Hello Dana", html: "<p>Hi Dana</p>" },
    "GET /api/campaigns/k1/candidates/": CANDIDATES,
    "GET /api/campaigns/k1/": CAMPAIGN,
    "GET /api/contact-types/": [],
    "GET /api/pipelines/": [],
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<CampaignDetail />, { path: "/campaigns/:id", route: "/campaigns/k1" });
  return fetchMock;
}

const posted = (fetchMock: ReturnType<typeof mockApi>, end: string) =>
  fetchMock.calls.filter((c) => c.method === "POST" && c.url.endsWith(end)).map((c) => c.body);

/** Owner, 2026-09-28 — compose once, choose people, enrol and queue. */
describe("the campaign composer", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("queues everyone chosen, minus who was deselected and who cannot be sent to", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "POST /api/campaigns/k1/queue/": { queued_count: 1, skipped: [] } });
    expect(await screen.findByLabelText("Include Left Early")).toBeDisabled();
    expect(screen.getByText("unsubscribed from marketing emails")).toBeInTheDocument();
    // Nobody is chosen until someone chooses.
    expect(screen.getByRole("button", { name: /Enrol and queue/ })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Select all 2" }));
    await user.click(screen.getByLabelText("Include Priya Shah"));
    await user.click(screen.getByRole("button", { name: "Enrol and queue 1" }));

    await waitFor(() => expect(posted(fetchMock, "/queue/")).toEqual([{ ids: ["c1"] }]));
    expect(await screen.findByText(/1 queued in the sending queue/)).toBeInTheDocument();
  });

  it("offers send-as-is only when writing raw HTML", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByLabelText("Email body");
    expect(screen.queryByLabelText(/Send as-is/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("tab", { name: "HTML" }));
    expect(screen.getByLabelText("Email HTML")).toHaveValue("<p>Hi {FirstName}</p>");
    expect(screen.getByLabelText(/Send as-is/)).not.toBeChecked();
  });

  it("previews unsaved edits, and will not queue until they are saved", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    const subject = await screen.findByLabelText("Subject");
    await user.clear(subject);
    await user.type(subject, "News for {{FirstName}");

    await waitFor(() => expect(posted(fetchMock, "/preview/").at(-1)).toMatchObject(
      { subject: "News for {FirstName}" }), { timeout: 3000 });
    expect(screen.getByRole("button", { name: /Enrol and queue/ })).toBeDisabled();
  });

  it("sends a test to the composer", async () => {
    const user = userEvent.setup();
    show({ "POST /api/campaigns/k1/test-send/": { to: "bryan@x.test", state: "sent" } });
    await user.click(await screen.findByRole("button", { name: "Send me a test" }));
    expect(await screen.findByText(/Test sent to bryan@x.test/)).toBeInTheDocument();
  });
});
