import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { EmailSettings } from "./EmailSettings";

function status(overrides: Record<string, unknown> = {}) {
  return {
    connected: true,
    email_address: "bryan@getexecutivesnow.com",
    scopes: ["https://www.googleapis.com/auth/gmail.send"],
    connected_at: "2026-09-10T00:00:00Z",
    tier2_enabled: false,
    alias: "info@getexecutivesnow.com",
    alias_verified: true,
    alias_verified_at: "2026-09-10T00:00:00Z",
    alias_listed: true,
    send_as: [],
    send_as_error: "",
    is_sending_connection: true,
    transport: "gmail",
    transport_label: "Your connected Gmail",
    practice_sending: { ok: true, detail: "", account: "bryan@getexecutivesnow.com" },
    oauth_configured: true,
    is_local_build: true,
    ...overrides,
  };
}

function setup(statusOverrides = {}, routes: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "/api/gmail-connection/": status(statusOverrides),
    "/api/dev-allowlist/effective/": {
      is_local: true,
      from_env: ["fromenv@example.invalid"],
      entries: [{ id: "e1", address: "fromdb@example.invalid", note: "me", removable: true }],
      effective: ["fromdb@example.invalid", "fromenv@example.invalid"],
    },
    "POST /api/dev-allowlist/": (body: unknown) => ({ status: 201, body }),
    ...routes,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<EmailSettings me={aMe()} />);
  return fetchMock;
}

describe("EmailSettings — dev delivery section", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the allow-list on a localhost build", async () => {
    setup();

    expect(await screen.findByText("Dev builds — who may receive real mail"))
      .toBeInTheDocument();
    expect(await screen.findByText("fromenv@example.invalid")).toBeInTheDocument();
    expect(screen.getByText("fromdb@example.invalid")).toBeInTheDocument();
  });

  it("marks .env entries as locked and database entries as removable", async () => {
    setup();

    expect(await screen.findByText("locked")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Remove fromdb@example.invalid" }))
      .toBeInTheDocument();
    // The environment is the floor: there is no Remove for an .env entry.
    expect(screen.queryByRole("button", { name: "Remove fromenv@example.invalid" }))
      .not.toBeInTheDocument();
  });

  it("does not exist at all on a non-localhost build", async () => {
    // The API 404s there too — this is the second of two independent locks.
    setup({ is_local_build: false });

    expect(await screen.findByText("Transport in use")).toBeInTheDocument();
    expect(screen.queryByText("Dev builds — who may receive real mail"))
      .not.toBeInTheDocument();
    expect(screen.queryByLabelText("Address to allow")).not.toBeInTheDocument();
  });

  it("adds an address", async () => {
    const user = userEvent.setup();
    const fetchMock = setup();

    await user.type(await screen.findByLabelText("Address to allow"), "new@example.invalid");
    await user.click(screen.getByRole("button", { name: "Allow real delivery" }));

    await waitFor(() => {
      const post = fetchMock.calls.find((c) => c.method === "POST");
      expect(post?.body).toMatchObject({ address: "new@example.invalid" });
    });
  });

  it("surfaces the H6 refusal for a wildcard", async () => {
    const user = userEvent.setup();
    setup({}, {
      "POST /api/dev-allowlist/": () => ({
        status: 400,
        body: { address: ["'@getexecutivesnow.com' is not an exact address. Wildcards and bare domains are rejected."] },
      }),
    });

    await user.type(await screen.findByLabelText("Address to allow"), "@getexecutivesnow.com");
    await user.click(screen.getByRole("button", { name: "Allow real delivery" }));

    expect(await screen.findByText(/not an exact address/)).toBeInTheDocument();
  });
});

describe("EmailSettings — collecting replies (FR-6.3g)", () => {
  beforeEach(() => vi.unstubAllGlobals());
  const READ = "https://www.googleapis.com/auth/gmail.readonly";
  const consent = { "POST /api/gmail-connection/start/": () => ({
    status: 200, body: { authorization_url: "#google-consent" } }) };

  it("offers the tick unticked when the connection cannot read mail", async () => {
    setup();

    const box = await screen.findByRole("checkbox", { name: "Also collect replies" });
    expect(box).not.toBeChecked();
    expect(screen.getByText(/does not hold it; tick the box and Reconnect/))
      .toBeInTheDocument();
  });

  it("starts the tick checked when the connection already reads mail", async () => {
    setup({ scopes: ["https://www.googleapis.com/auth/gmail.send", READ] });

    expect(await screen.findByRole("checkbox", { name: "Also collect replies" }))
      .toBeChecked();
  });

  it("asks for the read scope on Reconnect only when ticked", async () => {
    const user = userEvent.setup();
    const fetchMock = setup({}, consent);

    await user.click(await screen.findByRole("checkbox", { name: "Also collect replies" }));
    await user.click(screen.getByRole("button", { name: "Reconnect" }));

    await waitFor(() => {
      const post = fetchMock.calls.find((c) => c.method === "POST"
        && c.url.includes("/api/gmail-connection/start/"));
      expect(post?.body).toEqual({ inbound: true });
    });
  });

  it("connects without the read scope by default", async () => {
    const user = userEvent.setup();
    const fetchMock = setup({ connected: false, scopes: [] }, consent);

    await user.click(await screen.findByRole("button", { name: "Connect Gmail" }));

    await waitFor(() => {
      const post = fetchMock.calls.find((c) => c.method === "POST"
        && c.url.includes("/api/gmail-connection/start/"));
      expect(post?.body).toEqual({ inbound: false });
    });
  });
});
