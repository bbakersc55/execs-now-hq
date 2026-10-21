import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Replies } from "./Replies";

const HEALTH = { can_read: true, detail: "", account: "bryan@x.test",
                 threads_watched: 12, last_polled_at: "2026-09-22T17:45:00Z",
                 waiting: 1, errors: 0 };

const WAITING = {
  id: "u1", from_address: "nobody@elsewhere.invalid", from_name: "Someone Else",
  subject: "Re: Your progress report",
  body: "Forwarding this on — can you send me the detail?",
  reason: "no thread, and no contact holds nobody@elsewhere.invalid",
  state: "pending", received_at: "2026-09-22T10:09:00Z", filed_contact: null,
};

const CONTACTS = [{
  id: "c1", first_name: "Dana", last_name: "Reyes", title: "COO", company: null,
  owner: null, pipeline_positions: [], source: "", background: "", tags: [],
  emails: [{ id: "e1", address: "dana@acme.invalid", is_primary: true }],
  phones: [], type_codes: ["client"], referral_fee_terms: "", referral_cadence: "",
  referral_touch_mode: "template", referral_next_touch_at: null,
  referral_onboarded_at: null,
}];

function show(extra: Record<string, unknown> = {}, me = aMe()) {
  const fetchMock = mockApi({
    ...extra,
    "GET /api/unmatched-inbound/poll/": HEALTH,
    "GET /api/unmatched-inbound/": [WAITING],
    "GET /api/contacts/": CONTACTS,
    "GET /api/leave-requests/": [],
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Replies me={me} />, { path: "/replies", route: "/replies" });
  return fetchMock;
}

/**
 * Module 6's queue. **The failure mode this module is built against is
 * silence**, so the screen's job is to say what came back, why it could not be
 * placed, and to make placing it one choice.
 */
describe("replies that came back", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows what could not be placed, and why", async () => {
    show();

    expect(await screen.findByText("Re: Your progress report")).toBeInTheDocument();
    expect(screen.getByText(/Someone Else · nobody@elsewhere.invalid/))
      .toBeInTheDocument();
    // The reason, not a mystery.
    expect(screen.getByText(/no thread, and no contact holds/)).toBeInTheDocument();
    expect(screen.getByText(/can you send me the detail/)).toBeInTheDocument();
  });

  it("files it to a contact and offers to remember the address", async () => {
    const user = userEvent.setup();
    const fetchMock = show({
      "POST /api/unmatched-inbound/u1/file/": { id: "u1", state: "filed",
                                                message: "m1", thread: "t1" },
    });

    // Wait for the contacts to land: the select exists before they do.
    await screen.findByRole("option", { name: /Dana Reyes/ });
    await user.selectOptions(
      screen.getByRole("combobox",
                       { name: "File nobody@elsewhere.invalid to" }), "c1");
    await user.click(screen.getByRole("button",
                                      { name: "File nobody@elsewhere.invalid" }));

    await waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.url.endsWith("/file/"));
      // FR-6.8 — teaching the CRM the address is what makes the *next* reply
      // file itself, and it is on by default.
      expect(posted?.body).toEqual({ contact: "c1", add_address: true });
    });
    expect(await screen.findByText(/Filed to Dana Reyes/)).toBeInTheDocument();
  });

  it("will not file without a contact chosen", async () => {
    show();
    expect(await screen.findByRole("button",
                                   { name: "File nobody@elsewhere.invalid" }))
      .toBeDisabled();
  });

  it("says when it cannot read the mailbox at all", async () => {
    show({ "GET /api/unmatched-inbound/poll/": {
      ...HEALTH, can_read: false,
      detail: "The connected Google account has not granted permission to read mail." } });

    expect(await screen.findByText(/has not granted permission to read mail/))
      .toBeInTheDocument();    expect(screen.getByRole("link", { name: "Open Email settings" }))
      .toHaveAttribute("href", "/settings/email");
  });

  it("gives a VA the queue and not the mailbox", async () => {
    show({}, aMe({ role: "VA" }));

    // Matrix 12.3 — filing is the VA's job; reading the practice's mailbox
    // is the founder's.
    expect(await screen.findByRole("combobox",
                                   { name: "File nobody@elsewhere.invalid to" }))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Collect now/ }))
      .not.toBeInTheDocument();
  });

  it("says plainly when there is nothing waiting", async () => {
    show({ "GET /api/unmatched-inbound/": [] });

    expect(await screen.findByText(/Nothing waiting to be filed/)).toBeInTheDocument();
  });
});

describe("the Replies screen says what it is (2026-10-12)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("has one sentence under its title", async () => {
    show();
    expect(await screen.findByText(
      "Replies to mail the app sent, matched to your contacts; a reply that could not "
      + "be matched waits here to be filed.")).toHaveClass("sub");
  });
});

const ASKED = [{
  id: "r1", subject: "Re: Hello Dana", from_address: "dana@acme.invalid",
  received_at: "2026-10-19T10:05:00Z", said: "STOP",
  contact: { id: "c1", name: "Dana Reyes" },
  answered: { subject: "Hello Dana", producer: "campaign", sent_at: "2026-10-01T09:00:00Z" },
}];

/** Owner, 2026-10-19: a reply that asks to leave is marked; one click acts. */
describe("replies that ask to leave", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("marks them, and unsubscribes only on the click", async () => {
    const user = userEvent.setup();
    const fetchMock = show({ "GET /api/leave-requests/": ASKED,
                             "POST /api/leave-requests/r1/unsubscribe/": {
                               id: "r1", leave_request: "unsubscribed" } });
    const row = await screen.findByRole("group", { name: "Dana Reyes asked to leave" });
    expect(row).toHaveTextContent("Asked to leave");
    expect(row).toHaveTextContent("Re: Hello Dana");
    expect(row).toHaveTextContent("STOP");
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
    await user.click(screen.getByRole("button", { name: "Unsubscribe them" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.url)
      .toBe("/api/leave-requests/r1/unsubscribe/"));
    expect(await screen.findByText(/as the link in the email would do/)).toBeInTheDocument();
  });

  it("lets an assistant see them but not act", async () => {
    show({ "GET /api/leave-requests/": ASKED }, aMe({ role: "VA" }));
    await screen.findByRole("group", { name: "Dana Reyes asked to leave" });
    expect(screen.queryByRole("button", { name: "Unsubscribe them" })).toBeNull();
    expect(screen.getByText(/practice owner or an associate can unsubscribe/))
      .toBeInTheDocument();
  });
});
