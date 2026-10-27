import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { EmailSettings } from "./EmailSettings";

function provider(overrides: Record<string, unknown> = {}) {
  return {
    provider: "google",
    label: "Gmail",
    choices: [{ value: "google", label: "Gmail" }, { value: "microsoft", label: "Microsoft 365" }],
    can_switch: true,
    refusal: "",
    google_configured: true,
    microsoft_configured: true,
    ...overrides,
  };
}

function microsoft(overrides: Record<string, unknown> = {}) {
  return {
    provider: "microsoft",
    connected: false,
    email_address: "",
    scopes: [],
    connected_at: null,
    reads_mail: false,
    alias: "info@contoso.example",
    alias_verified: false,
    alias_verified_at: null,
    send_as_error: "",
    is_sending_connection: false,
    practice_sending: { ok: false, detail: "No Microsoft 365 account is connected.", account: "" },
    configured: true,
    refusal: "",
    is_local_build: false,
    ...overrides,
  };
}

const GMAIL = {
  connected: false, email_address: "", scopes: [], connected_at: null, tier2_enabled: false,
  alias: "info@getexecutivesnow.com", alias_verified: false, alias_verified_at: null,
  alias_listed: false, send_as: [], send_as_error: "", is_sending_connection: false,
  transport: "gmail", transport_label: "Your connected Gmail",
  practice_sending: { ok: false, detail: "No Gmail account is connected.", account: "" },
  oauth_configured: true, is_local_build: false,
};

function setup(routes: Record<string, unknown>, me = aMe(), route = "/") {
  // Sender defaults are their own screen's concern, unstubbed as in
  // EmailSettings.test.tsx.
  const fetchMock = mockApi(routes);
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<EmailSettings me={me} />, { path: "/", route });
  return fetchMock;
}

describe("Mail goes through", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows Gmail's screen with the switch on a Gmail practice", async () => {
    setup({ "/api/mail-provider/": provider(), "/api/gmail-connection/": GMAIL });
    expect(await screen.findByText("Mail goes through")).toBeInTheDocument();
    expect(await screen.findByText("Your Gmail connection")).toBeInTheDocument();
    expect(screen.queryByText("Your Microsoft 365 connection")).not.toBeInTheDocument();
  });

  it("asks before switching, says what it means, and switches", async () => {
    const user = userEvent.setup();
    let current = provider();
    const fetchMock = setup({
      "/api/mail-provider/switch/": () => {
        current = provider({ provider: "microsoft", label: "Microsoft 365" });
        return { body: current };
      },
      "/api/mail-provider/": () => ({ body: current }),
      "/api/gmail-connection/": GMAIL,
      "/api/microsoft-connection/": microsoft(),
    });

    await user.click(await screen.findByRole("radio", { name: "Microsoft 365" }));
    expect(screen.getByText(/nothing sends until a Microsoft 365 account is connected/))
      .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Switch to Microsoft 365" }));

    expect(await screen.findByText("Your Microsoft 365 connection")).toBeInTheDocument();
    const post = fetchMock.calls.find((c) => c.url === "/api/mail-provider/switch/");
    expect(post?.method).toBe("POST");
    expect(post?.body).toEqual({ provider: "microsoft" });
  });

  it("lets an associate see the transport but not switch it", async () => {
    setup({
      "/api/mail-provider/": provider({ can_switch: false }),
      "/api/gmail-connection/": GMAIL,
    }, aMe({ role: "CF" }));
    expect(await screen.findByText("The practice owner chooses this.")).toBeInTheDocument();
    expect(screen.queryByRole("radio", { name: "Microsoft 365" })).not.toBeInTheDocument();
  });

  it("falls back to Gmail's screen when the server cannot say", async () => {
    setup({ "/api/gmail-connection/": GMAIL });
    expect(await screen.findByText("Your Gmail connection")).toBeInTheDocument();
    expect(screen.queryByText("Mail goes through")).not.toBeInTheDocument();
  });
});

describe("Microsoft 365 email settings", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const onMicrosoft = provider({ provider: "microsoft", label: "Microsoft 365" });

  it("connects, asking to read mail only when ticked", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, set href(v: string) { assign(v); } });
    const fetchMock = setup({
      "/api/mail-provider/": onMicrosoft,
      "/api/microsoft-connection/start/": { authorization_url: "https://login.microsoftonline.com/x" },
      "/api/microsoft-connection/": microsoft(),
    });

    expect(await screen.findByText(/No Microsoft 365 account is connected for you/))
      .toBeInTheDocument();
    await user.click(screen.getByRole("checkbox", { name: "Also collect replies" }));
    await user.click(screen.getByRole("button", { name: "Connect Microsoft 365" }));

    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://login.microsoftonline.com/x"));
    const start = fetchMock.calls.find((c) => c.url === "/api/microsoft-connection/start/");
    expect(start?.body).toEqual({ inbound: true });
  });

  it("shows the connected account and the address check", async () => {
    setup({
      "/api/mail-provider/": onMicrosoft,
      "/api/microsoft-connection/": microsoft({
        connected: true, email_address: "bryan@contoso.example",
        scopes: ["Mail.Send", "Mail.ReadBasic", "User.Read"],
        connected_at: "2026-10-27T15:00:00Z",
        alias_verified: true, alias_verified_at: "2026-10-27T15:01:00Z",
        is_sending_connection: true,
        practice_sending: { ok: true, detail: "", account: "bryan@contoso.example" },
      }),
    });
    expect(await screen.findByText("practice sending account")).toBeInTheDocument();
    expect(screen.getByText("passed")).toBeInTheDocument();
    expect(screen.getByText(/Send mail as you · See who sent a message/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check again" })).toBeInTheDocument();
  });

  it("says why an address check failed, and that nothing sends", async () => {
    setup({
      "/api/mail-provider/": onMicrosoft,
      "/api/microsoft-connection/": microsoft({
        connected: true, email_address: "bryan@contoso.example",
        send_as_error: "Microsoft 365 sent the check from bryan@contoso.example, not info@contoso.example.",
      }),
    });
    expect(await screen.findByText(/sent the check from bryan@contoso.example/))
      .toBeInTheDocument();
    expect(screen.getByText(/deliberately no fallback to your/)).toBeInTheDocument();
  });

  it("shows Microsoft's refusal from the redirect", async () => {
    setup({
      "/api/mail-provider/": onMicrosoft,
      "/api/microsoft-connection/": microsoft(),
    }, aMe(), "/?ms_error=Microsoft%20reported%3A%20AADSTS90094");
    expect(await screen.findByText("Microsoft reported: AADSTS90094")).toBeInTheDocument();
  });

  it("on the demo, shows Microsoft 365 but connects nothing", async () => {
    const refusal = "This is the demo. It sends through its own Gmail connection only, so " +
      "Microsoft 365 can be seen here but not connected.";
    setup({
      "/api/mail-provider/": provider({ can_switch: false, refusal }),
      "/api/gmail-connection/": GMAIL,
    });
    expect(await screen.findByText(refusal)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Switch to/ })).not.toBeInTheDocument();
  });
});
