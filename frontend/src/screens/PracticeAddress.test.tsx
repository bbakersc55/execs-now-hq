import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Me } from "../lib/api";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { EmailSettings } from "./EmailSettings";

const OWNER = aMe({ role: "FF", email: "shawn@bluesky.invalid" });

function status(overrides: Record<string, unknown> = {}) {
  return {
    connected: false, email_address: "", scopes: [], connected_at: null,
    tier2_enabled: false, alias: "info@bluesky.invalid", alias_verified: false,
    alias_verified_at: null, alias_listed: false, send_as: [], send_as_error: "",
    is_sending_connection: false, transport: "gmail", transport_label: "Your connected Gmail",
    practice_sending: { ok: false, detail: "", account: "" },
    oauth_configured: true, is_local_build: false,
    ...overrides,
  };
}
const CONNECTED = { connected: true, email_address: "shawn@bluesky.invalid",
                    alias_verified: true, alias_listed: true };

function show(me: Me = OWNER, now: Record<string, unknown> = {},
              saved?: (body: { address: string }) => Record<string, unknown>) {
  const fetchMock = mockApi({
    "POST /api/gmail-connection/practice-address/": (body: unknown) => ({
      body: status({ ...now, alias: (body as { address: string }).address,
                     ...(saved?.(body as { address: string }) ?? {}) }) }),
    "/api/gmail-connection/": status(now),
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<EmailSettings me={me} />);
  return fetchMock;
}

const posted = (fetchMock: ReturnType<typeof mockApi>) =>
  fetchMock.calls.filter((c) => c.url.endsWith("/practice-address/")).map((c) => c.body);

/** Choosing the practice address (beta feedback, 2026-10-05, item B). */
describe("the practice address", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("asks its questions before Connect, starting from the sign-in address", async () => {
    show();

    expect(await screen.findByLabelText("What is your email?"))
      .toHaveValue("shawn@bluesky.invalid");
    const card = screen.getByRole("heading", { name: "Practice address" }).closest("section")!;
    const connect = screen.getByRole("heading", { name: "Your Gmail connection" })
      .closest("section")!;
    expect(card.compareDocumentPosition(connect) & Node.DOCUMENT_POSITION_FOLLOWING)
      .toBeTruthy();
  });

  it("recommends a separate address and suggests info@, without requiring it", async () => {
    show(OWNER, { alias: "shawn@bluesky.invalid" });   // nothing chosen beyond their own

    const separate = await screen.findByRole("radio", { name: /A separate practice address/ });
    expect(separate.closest("label")).toHaveTextContent("recommended");
    expect(screen.getByRole("radio", { name: "Use my own email" })).toBeChecked();

    await userEvent.setup().click(separate);
    expect(screen.getByLabelText("Practice address")).toHaveValue("info@bluesky.invalid");
  });

  it("saves the owner's own email as the practice address, with nothing to set up", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await user.click(await screen.findByRole("radio", { name: "Use my own email" }));

    expect(screen.getByText(/Nothing to set up in Gmail/)).toBeInTheDocument();
    // The alias-or-inbox question is only for a separate address.
    expect(screen.queryByText(/separate inbox or an alias/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save shawn@bluesky.invalid" }));

    await waitFor(() => expect(posted(fetchMock)).toEqual([{ address: "shawn@bluesky.invalid" }]));
    expect(await screen.findByText(/will be checked when you connect Gmail/)).toBeInTheDocument();
  });

  it("lets a separate address be anything, such as helpdesk@", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    const box = await screen.findByLabelText("Practice address");
    expect(box).toHaveValue("info@bluesky.invalid");

    await user.clear(box);
    await user.type(box, "HelpDesk@bluesky.invalid");
    await user.click(screen.getByRole("button", { name: "Save helpdesk@bluesky.invalid" }));

    await waitFor(() =>
      expect(posted(fetchMock)).toEqual([{ address: "helpdesk@bluesky.invalid" }]));
  });

  it("says what an inbox costs and what an alias does not, and how to add an alias", async () => {
    show();
    const question = (await screen.findByText(/Do you want a separate inbox or an alias/))
      .closest("fieldset")!;

    expect(question).toHaveTextContent(/separate inbox is an extra charge with Google or Microsoft/);
    expect(question).toHaveTextContent(/alias costs nothing extra/);
    expect(within(question).getByRole("radio", { name: "An alias" })).toBeChecked();
    expect(question).toHaveTextContent(/admin\.google\.com/);
    expect(question).toHaveTextContent(/Alternate email addresses/);
    expect(question).toHaveTextContent(/Send mail as/);
    expect(question).toHaveTextContent(/info@bluesky\.invalid/);
  });

  it("is plain about a separate inbox: sends, no replies yet, Google only", async () => {
    const user = userEvent.setup();
    show();
    await user.click(await screen.findByRole("radio", { name: "A separate inbox" }));
    const question = screen.getByText(/Do you want a separate inbox or an alias/)
      .closest("fieldset")!;

    expect(question).toHaveTextContent(/send from it once it is in your Gmail Send mail as list/);
    expect(question).toHaveTextContent(/Replies sent to that inbox will not appear in client records/);
    expect(question).toHaveTextContent(/second account is planned and not built yet/);
    expect(question).toHaveTextContent(/connects to Google only today/);
    expect(question).toHaveTextContent(/Microsoft 365 inbox cannot be connected/);
  });

  it("shows Gmail's answer when the new address is not on the account", async () => {
    const user = userEvent.setup();
    show(OWNER, { ...CONNECTED, alias_verified: false }, () => ({
      alias_verified: false,
      verify_error: "helpdesk@bluesky.invalid is not a send-as address on shawn@bluesky.invalid.",
    }));
    const box = await screen.findByLabelText("Practice address");
    await user.clear(box);
    await user.type(box, "helpdesk@bluesky.invalid");
    await user.click(screen.getByRole("button", { name: "Save helpdesk@bluesky.invalid" }));

    expect(await screen.findByText(/is not a send-as address on shawn@bluesky.invalid/))
      .toBeInTheDocument();
    // Still open: it is not working yet.
    expect(screen.getByLabelText("What is your email?")).toBeInTheDocument();
  });

  it("keeps an existing practice's address, shown with a way to change it", async () => {
    const user = userEvent.setup();
    const fetchMock = show(OWNER, CONNECTED);

    const card = (await screen.findByRole("heading", { name: "Practice address" }))
      .closest("section")!;
    expect(card).toHaveTextContent("info@bluesky.invalid");
    expect(within(card).queryByLabelText("What is your email?")).not.toBeInTheDocument();
    expect(posted(fetchMock)).toEqual([]);

    await user.click(within(card).getByRole("button", { name: "Change" }));
    expect(screen.getByLabelText("Practice address")).toHaveValue("info@bluesky.invalid");
    expect(screen.getByRole("radio", { name: /A separate practice address/ })).toBeChecked();
  });

  it("confirms and closes when the saved address is verified", async () => {
    const user = userEvent.setup();
    show(OWNER, CONNECTED);
    await user.click(await screen.findByRole("button", { name: "Change" }));
    await user.click(screen.getByRole("radio", { name: "Use my own email" }));
    await user.click(screen.getByRole("button", { name: "Save shawn@bluesky.invalid" }));

    expect(await screen.findByText("shawn@bluesky.invalid is verified. App mail will send as it."))
      .toBeInTheDocument();
    expect(screen.queryByLabelText("What is your email?")).not.toBeInTheDocument();
    expect(screen.getByText("your own email")).toBeInTheDocument();
  });

  it("is the practice owner's: an associate sees no questions", async () => {
    show(aMe({ role: "CF", email: "casey@bluesky.invalid" }));
    await screen.findByRole("heading", { name: "Your Gmail connection" });
    expect(screen.queryByRole("heading", { name: "Practice address" })).not.toBeInTheDocument();
    expect(screen.queryByLabelText("What is your email?")).not.toBeInTheDocument();
  });
});
