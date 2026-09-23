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
  referral_touch_mode: "ai", referral_next_touch_at: null,
  referral_onboarded_at: null,
}];

function show(extra: Record<string, unknown> = {}, me = aMe()) {
  const fetchMock = mockApi({
    "GET /api/unmatched-inbound/poll/": HEALTH,
    "GET /api/unmatched-inbound/": [WAITING],
    "GET /api/contacts/": CONTACTS,
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
      .toBeInTheDocument();
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
