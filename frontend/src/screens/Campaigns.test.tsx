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

const PIPELINES = [{ id: "p1", name: "Referral", kind: "referral", stages: [
  { id: "s1", label: "Contact", code: "contact" }, { id: "s2", label: "Engaged", code: "engaged" }] }];

function show(extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    "POST /api/campaigns/k1/preview/": { subject: "Hello Dana", html: "<p>Hi Dana</p>" },
    "GET /api/campaigns/k1/candidates/": CANDIDATES,
    "GET /api/campaigns/k1/": CAMPAIGN,
    "GET /api/contact-types/": [],
    "GET /api/pipelines/": PIPELINES,
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
    expect(screen.getByRole("button", { name: /Enroll and queue/ })).toBeDisabled();
    // The count of everyone shown; the header's box takes only the sendable,
    // clears them all again, and per-person ticks work under it.
    expect(screen.getByLabelText("How many")).toHaveTextContent(
      "3 shown · 0 of 2 chosen · 1 cannot be sent to");
    const all = screen.getByRole("checkbox", { name: "Select all 2" });
    await user.click(all);
    expect(all).toBeChecked();
    expect(screen.getByLabelText("How many")).toHaveTextContent("2 of 2 chosen");
    await user.click(all);
    expect(screen.getByLabelText("How many")).toHaveTextContent("0 of 2 chosen");
    await user.click(all);
    await user.click(screen.getByLabelText("Include Priya Shah"));
    expect(all).not.toBeChecked();
    expect((all as HTMLInputElement).indeterminate).toBe(true);
    await user.click(screen.getByRole("button", { name: "Enroll and queue 1" }));

    await waitFor(() => expect(posted(fetchMock, "/queue/")).toEqual([{ ids: ["c1"] }]));
    expect(await screen.findByText(/1 queued in the sending queue/)).toBeInTheDocument();
  });

  it("starts from a template by copying its subject, words and fallback", async () => {
    const user = userEvent.setup();
    const fetchMock = show({
      "PATCH /api/campaigns/k1/": CAMPAIGN,
      "GET /api/email-templates/": [{ id: "t1", name: "Proposal nudge", kind: "general",
        subject: "Following up, {FirstName}", body: "Hi {FirstName},\n\nA & B.\nThanks.",
        first_name_fallback: "friend", original: "", is_original: false, changed: false,
        used_for: [], updated_at: "2026-10-20T12:00:00Z" }],
    });
    const start = await screen.findByLabelText("Start from a template");
    await waitFor(() => expect(start.querySelectorAll("option")).toHaveLength(2));
    await user.selectOptions(start, "t1");
    expect(screen.getByLabelText("Subject")).toHaveValue("Following up, {FirstName}");
    expect(screen.getByText(/Copied from “Proposal nudge”/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /^Save$/ }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toMatchObject({ subject: "Following up, {FirstName}", first_name_fallback: "friend",
                       body_html: "<p>Hi {FirstName},</p><p>A &amp; B.<br>Thanks.</p>" }));
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
    expect(screen.getByRole("button", { name: /Enroll and queue/ })).toBeDisabled();
  });

  it("sends a test to the composer", async () => {
    const user = userEvent.setup();
    show({ "POST /api/campaigns/k1/test-send/": { to: "bryan@x.test", state: "sent" } });
    await user.click(await screen.findByRole("button", { name: "Send me a test" }));
    expect(await screen.findByText(/Test sent to bryan@x.test/)).toBeInTheDocument();
  });
});

/** Owner, 2026-10-19: the campaign's files, and what happens when it is sent. */
describe("campaign follow-through", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("saves a stage to move them to and a referral-touch cadence", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "PATCH /api/campaigns/k1/": { ...CAMPAIGN, on_sent_stage: "s2",
                                                           on_sent_pipeline: "p1",
                                                           on_sent_cadence: "quarterly" } });
    await user.selectOptions(await screen.findByLabelText("Pipeline to move them in"), "p1");
    await user.selectOptions(screen.getByLabelText("Stage to move them to"), "s2");
    await user.selectOptions(screen.getByLabelText("Referral touches cadence"), "quarterly");
    expect(screen.getByText(/Only referral partners are put on referral touches/))
      .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toMatchObject({ on_sent_stage: "s2", on_sent_cadence: "quarterly" }));
  });

  it("adds a file, and offers no more than three", async () => {
    const user = userEvent.setup();
    const one = { ...CAMPAIGN, attachments: [{ id: "f1", filename: "flyer.pdf",
                                               byte_size: 20480 }] };
    const fetchMock = show({ "POST /api/campaigns/k1/attachments/": one });
    await user.upload(await screen.findByLabelText("Add a file"),
                      new File(["%PDF"], "flyer.pdf", { type: "application/pdf" }));
    expect(await screen.findByText("flyer.pdf")).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.url.endsWith("/attachments/"))?.method).toBe("POST");
  });

  it("has no file box once there are three", async () => {
    const three = { ...CAMPAIGN, attachments: ["a", "b", "c"].map((n) => (
      { id: n, filename: `${n}.pdf`, byte_size: 1024 })) };
    vi.stubGlobal("fetch", mockApi({
      "POST /api/campaigns/k1/preview/": { subject: "", html: "" },
      "GET /api/campaigns/k1/candidates/": [], "GET /api/campaigns/k1/": three,
      "GET /api/contact-types/": [], "GET /api/pipelines/": PIPELINES }));
    renderRoute(<CampaignDetail />, { path: "/campaigns/:id", route: "/campaigns/k1" });
    expect(await screen.findAllByText(/^[abc]\.pdf$/)).toHaveLength(3);
    expect(screen.queryByLabelText("Add a file")).toBeNull();
  });
});

/** Owner, 2026-10-20: the test copy, the preview and the first-name fallback. */
describe("the test copy and the first-name fallback", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("saves what a missing first name becomes, and lists the files under the preview",
    async () => {
      const user = userEvent.setup();
      const withFile = { ...CAMPAIGN, first_name_fallback: "there",
                         attachments: [{ id: "f1", filename: "flyer.pdf", byte_size: 2048 }] };
      const fetchMock = mockApi({
        "PATCH /api/campaigns/k1/": { ...withFile, first_name_fallback: "friend" },
        "POST /api/campaigns/k1/preview/": { subject: "Hello [First name]",
                                             html: "<p>Hi [First name]</p>" },
        "GET /api/campaigns/k1/candidates/": CANDIDATES, "GET /api/campaigns/k1/": withFile,
        "GET /api/contact-types/": [], "GET /api/pipelines/": PIPELINES });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<CampaignDetail />, { path: "/campaigns/:id", route: "/campaigns/k1" });
      expect(await screen.findByLabelText("Attached files")).toHaveTextContent(
        "Attached: flyer.pdf");
      expect(await screen.findByText("Hello [First name]")).toBeInTheDocument();
      const box = screen.getByLabelText("If a first name is missing, use");
      expect(box).toHaveValue("there");
      await user.clear(box);
      await user.type(box, "friend");
      await user.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
        .toMatchObject({ first_name_fallback: "friend" }));
    });

  it("names who has no first name before queueing, and queues on the yes", async () => {
    const user = userEvent.setup();
    let asked = 0;
    const fetchMock = show({ "POST /api/campaigns/k1/queue/": (body: unknown) => {
      asked += 1;
      return (body as { confirm_missing_names?: boolean }).confirm_missing_names
        ? { status: 201, body: { queued_count: 2, skipped: [] } }
        : { status: 409, body: { detail: "1 of them has no first name.",
                                 missing_first_names: [{ id: "c2", name: "Okafor" }],
                                 fallback: "there" } };
    } });
    await user.click(await screen.findByRole("checkbox", { name: "Select all 2" }));
    await user.click(screen.getByRole("button", { name: "Enroll and queue 2" }));
    expect(await screen.findByRole("alert", { name: "Recipients with no first name" }))
      .toHaveTextContent("1 of them has no first name, so {FirstName} will read “there”: Okafor.");
    await user.click(screen.getByRole("button", { name: "Queue anyway" }));
    expect(await screen.findByText(/2 queued in the sending queue/)).toBeInTheDocument();
    expect(asked).toBe(2);
    expect(posted(fetchMock, "/queue/").at(-1)).toMatchObject({ confirm_missing_names: true });
  });
});
