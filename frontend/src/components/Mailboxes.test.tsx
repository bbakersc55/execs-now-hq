import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MailItem, Mailbox, Mailboxes } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { DefaultMailbox, MailTab, MailboxesCard } from "./Mailboxes";

function box(over: Partial<Mailbox>): Mailbox {
  return {
    id: "m1", provider: "gmail", provider_label: "Gmail", kind: "own", kind_label: "Someone's own",
    label: "Bryan's own", email_address: "bryan@getexecutivesnow.com", whose: "Bryan Baker",
    company: null, company_name: "", connected: true, sends_as: "bryan@getexecutivesnow.com",
    send_as_address: "info@getexecutivesnow.com", send_as_verified: true, send_as_error: "",
    reads: true, files_mail: false, files_after: null, files_error: "", last_poll_error: "",
    connected_by: "Bryan Baker", disconnected_at: null, may_change: true, allowlist: [],
    ...over,
  };
}

const TWO: Mailboxes = {
  default: null, is_local_build: false,
  mailboxes: [box({}), box({ id: "m2", kind: "shared", kind_label: "A shared address",
    label: "Info", email_address: "hello@shared.invalid", sends_as: "hello@shared.invalid",
    send_as_address: "hello@shared.invalid" })],
};

function mail(over: Partial<MailItem>): MailItem {
  return {
    id: "e1", direction: "inbound", from_address: "dana@hooli.invalid",
    to_addresses: ["ops@hooli-box.invalid"], cc_addresses: [], subject: "Schedule",
    when: "2026-10-28T15:00:00Z", snippet: "Can we move Friday?", body: "Can we move Friday?",
    mailbox: { id: "m3", label: "Hooli ops", address: "ops@hooli-box.invalid" },
    contact: "c1", may_reply: true, reply_from: "ops@hooli-box.invalid", reply_refusal: "",
    ...over,
  };
}

describe("mailboxes (2026-10-28)", () => {
  it("lists every mailbox and disconnects a shared one", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/mailboxes/": TWO,
      "POST /api/mailboxes/m2/disconnect/": { ...TWO, mailboxes: [TWO.mailboxes[0],
        { ...TWO.mailboxes[1], connected: false, disconnected_at: "2026-10-28T16:00:00Z" }] },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<MailboxesCard />);
    expect(await screen.findByText("Info")).toBeInTheDocument();
    expect(screen.getByText("Bryan's own")).toBeInTheDocument();
    // Someone's own is managed on their connection above, not here.
    expect(screen.queryByRole("button", { name: "Disconnect bryan@getexecutivesnow.com" })).toBeNull();
    await user.click(screen.getByRole("button", { name: "Disconnect hello@shared.invalid" }));
    expect(await screen.findByText(/Nothing is sent through it or read from it now/)).toBeInTheDocument();
    expect(screen.getByText("disconnected")).toBeInTheDocument();
  });

  it("connects another mailbox by signing in as it", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/mailboxes/": TWO,
      "GET /api/companies/": [{ id: "co1", name: "Hooli Field Services" }],
      "POST /api/mailboxes/start/": { authorization_url: "about:blank" },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<MailboxesCard />);
    await user.click(await screen.findByRole("button", { name: "Connect another mailbox" }));
    await user.selectOptions(screen.getByLabelText("Whose mailbox"), "client");
    const go = screen.getByRole("button", { name: "Sign in to the mailbox" });
    expect(go).toBeDisabled();
    await user.selectOptions(await screen.findByLabelText("Client"), "co1");
    await user.type(screen.getByLabelText("Mailbox name"), "Hooli ops");
    await user.click(go);
    const started = fetchMock.calls.find((c) => c.url === "/api/mailboxes/start/");
    expect(started?.body).toMatchObject({ kind: "client", company: "co1", label: "Hooli ops",
      inbound: true, files_mail: false });
  });

  it("offers a default mailbox once there is more than one", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "GET /api/mailboxes/": TWO,
      "POST /api/mailboxes/default/": { ...TWO, default: "m2" } });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<DefaultMailbox />);
    await user.selectOptions(await screen.findByLabelText("My default mailbox"), "m2");
    expect(fetchMock.calls.find((c) => c.url === "/api/mailboxes/default/")?.body)
      .toEqual({ mailbox: "m2" });
  });

  it("shows a company's mail newest first and replies through its thread's mailbox", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/mail/": { results: [mail({}), mail({ id: "e2", direction: "outbound",
        subject: "Invoice INV-7", may_reply: false,
        reply_refusal: "An invoice's mail is answered from the invoice." })],
        page: 1, previous: false, next: false },
      "GET /api/mailboxes/company/": { mailbox: null, options: [] },
      "POST /api/mail/reply/": { state: "sent", detail: "Sent from ops@hooli-box.invalid." },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<MailTab me={aMe({ role: "FF" })} company="co1" />);
    const items = await screen.findAllByRole("button", { expanded: false });
    expect(items.map((b) => within(b).getByText(/Schedule|Invoice/).textContent))
      .toEqual(["Schedule", "Invoice INV-7"]);
    expect(screen.getAllByText(/Hooli ops/).length).toBeGreaterThan(0);
    await user.click(items[0]);
    await user.click(screen.getByRole("button", { name: "Reply" }));
    expect(screen.getByLabelText("Reply from ops@hooli-box.invalid")).toBeInTheDocument();
    await user.type(screen.getByLabelText("Reply from ops@hooli-box.invalid"), "Friday is fine.");
    await user.click(screen.getByRole("button", { name: "Send reply" }));
    expect(await screen.findByText("Sent from ops@hooli-box.invalid.")).toBeInTheDocument();
    expect(fetchMock.calls.find((c) => c.url === "/api/mail/reply/")?.body)
      .toEqual({ message: "e1", body_text: "Friday is fine." });
  });

  it("says why an assistant sees no mail for a client they are not assigned to", async () => {
    vi.stubGlobal("fetch", mockApi({
      "GET /api/mail/": () => ({ status: 403, body: { detail: "Mail is for the assistants assigned to this client." } }),
    }));
    renderRoute(<MailTab me={aMe({ role: "VA" })} company="co1" />);
    expect(await screen.findByText("Mail is for the assistants assigned to this client."))
      .toBeInTheDocument();
  });
});
