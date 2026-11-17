import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SessionEndsBanner, TwoFactorCard, TwoFactorPrompt } from "../components/TwoFactor";
import { PeopleScopePage } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { PeopleScope } from "./People";

/** 2026-11-17: two-factor sign-in, the twelve hours, and People's pages. */

const sent = (fetchMock: ReturnType<typeof mockApi>, suffix: string) =>
  fetchMock.calls.filter((c) => c.method !== "GET" && c.url.endsWith(suffix)).map((c) => c.body);

beforeEach(() => { vi.unstubAllGlobals(); });

describe("two-factor sign-in", () => {
  it("asks for the code after sign-in, or a backup code", async () => {
    const fetchMock = mockApi({ "POST /api/me/two-factor/verify": () => ({ body: {
      verified: true } }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<TwoFactorPrompt email="dana@example.invalid" />);
    await userEvent.type(screen.getByLabelText("Code from your authenticator app"), "12a3456");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() => expect(sent(fetchMock, "/verify")).toEqual([{ code: "123456" }]));
    await userEvent.click(screen.getByRole("button", { name: "Use a backup code" }));
    expect(screen.getByLabelText("Backup code")).toBeInTheDocument();
  });

  it("is set up with a QR code and the key, a code, and ten backup codes shown once",
     async () => {
    const codes = Array.from({ length: 10 }, (_, i) => `abcd-ef${i}${i}`);
    const fetchMock = mockApi({
      "POST /api/me/two-factor/start": () => ({ body: { key: "ABCD EFGH IJKL",
        uri: "otpauth://totp/x", qr_svg: "<svg><title>QR</title></svg>" } }),
      "POST /api/me/two-factor/confirm": () => ({ body: { enabled: true, since: "2026-11-17",
        backup_codes_left: 10, required: true, demo: false, backup_codes: codes } }),
      "GET /api/me/two-factor": { enabled: false, since: null, backup_codes_left: 0,
                                  required: true, demo: false },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<TwoFactorCard />);
    expect(await screen.findByText(/Required for you: you hold an HR permission/))
      .toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Set up two-factor sign-in" }));
    expect(await screen.findByLabelText("QR code")).toBeInTheDocument();
    expect(screen.getByLabelText("Key to type")).toHaveTextContent("ABCD EFGH IJKL");
    await userEvent.type(screen.getByLabelText("Code from your authenticator app"), "654321");
    await userEvent.click(screen.getByRole("button", { name: "Turn it on" }));
    const shown = await screen.findByLabelText("Your backup codes");
    expect(within(shown).getAllByRole("listitem")).toHaveLength(10);
    await userEvent.click(screen.getByRole("button", { name: "I have saved them" }));
    expect(screen.queryByLabelText("Your backup codes")).toBeNull();
    // Required: on, it can't be turned off.
    expect(screen.queryByRole("button", { name: "Turn it off" })).toBeNull();
  });

  it("says in the demo that it is never asked for", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/me/two-factor": {
      enabled: false, since: null, backup_codes_left: 0, required: false, demo: true } }));
    renderRoute(<TwoFactorCard />);
    expect(await screen.findByText(/never asked for at sign-in or on People screens/))
      .toBeInTheDocument();
  });
});

describe("the twelve hours", () => {
  it("warns in the last ten minutes, not before", () => {
    const soon = new Date(Date.now() + 8 * 60_000).toISOString();
    const { rerender } = render(<SessionEndsBanner endsAt={soon} />);
    expect(screen.getByRole("status", { name: "Signing out soon" }))
      .toHaveTextContent("12 hours after you signed in");
    rerender(<SessionEndsBanner endsAt={new Date(Date.now() + 3 * 3600_000).toISOString()} />);
    expect(screen.queryByRole("status", { name: "Signing out soon" })).toBeNull();
  });
});

describe("People pages", () => {
  const ACME = "11111111-2222-4333-8444-555555555555";
  const page = (more: Partial<PeopleScopePage> = {}): PeopleScopePage => ({
    guidance: "HR guidance, not legal advice", key: ACME, name: "Acme Fasteners",
    level: "generalist", level_label: "HR Generalist", manages: false, may_add: false,
    may_export: true, members: [],
    records: [{ id: "p1", name: "Marvin Placeholder", first_name: "Marvin",
                last_name: "Placeholder", title: "Plant manager", team: "Plant",
                work_email: "marvin@acme.example", manager: null, own: false,
                placeholder: true, masked: true,
                sensitive: { pay_rate: "•••••", home_address: "•••••", date_of_birth: "•••••",
                             personal_phone: "•••••", personal_email: "•••••",
                             emergency_contact: "•••••", documents: "1 document" } }],
    ...more });

  function show(routes: Record<string, unknown>) {
    const fetchMock = mockApi(routes);
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<PeopleScope />, { path: "/people/:scope", route: `/people/${ACME}` });
    return fetchMock;
  }

  it("says HR guidance, not legal advice, and masks for a Generalist", async () => {
    show({ [`GET /api/people/${ACME}/`]: page() });
    expect(await screen.findByText("Masked")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("HR guidance, not legal advice.");
    expect(screen.getByText("Your access: HR Generalist")).toBeInTheDocument();
    expect(screen.queryByRole("tab", { name: "Access log" })).toBeNull();
  });

  it("shows the directory only to senior leadership", async () => {
    const directory = page({ level: "directory", level_label: "Senior leadership (directory)",
                             may_export: false });
    directory.records = directory.records.map(({ sensitive: _s, masked: _m, ...r }) => r);
    show({ [`GET /api/people/${ACME}/`]: directory });
    expect(await screen.findByText("Directory only")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Export (CSV)" })).toBeNull();
  });

  it("sends an HR holder without two-factor to Profile first", async () => {
    show({ [`GET /api/people/${ACME}/`]: () => ({ status: 403, body: {
      two_factor: "enroll", detail: "Set up two-factor sign-in first, under Profile." } }) });
    expect(await screen.findByRole("link", { name: "Go to Profile" })).toHaveAttribute(
      "href", "/profile");
    expect(screen.getByRole("note")).toHaveTextContent("HR guidance, not legal advice.");
  });

  it("asks for the code again after four hours, then shows the page", async () => {
    let asked = 0;
    const fetchMock = show({
      "POST /api/me/two-factor/verify": () => ({ body: { verified: true } }),
      [`GET /api/people/${ACME}/`]: () => (asked++ === 0
        ? { status: 403, body: { two_factor: "recheck", detail: "Enter the code again." } }
        : { body: page() }),
    });
    await userEvent.type(await screen.findByLabelText("Code from your authenticator app"),
                         "123456");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByText("Marvin Placeholder")).toBeInTheDocument();
    expect(sent(fetchMock, "/verify")).toEqual([{ code: "123456" }]);
  });

  it("gives the owner the permissions and the access log", async () => {
    show({
      [`GET /api/people/${ACME}/permissions/`]: { guidance: "", grants: [{
        id: "g1", user: "Casey Associate", email: "casey@x.invalid", level: "generalist",
        level_label: "HR Generalist", scope: ACME, scope_label: "Acme Fasteners",
        granted_at: "2026-11-17", two_factor: false }], grantable: [], may_grant_all: true },
      [`GET /api/people/${ACME}/access-log/`]: { guidance: "", entries: [{
        at: "2026-11-17T10:00:00Z", who: "Bryan Baker", person: "Marvin Placeholder",
        action: "view", action_label: "Viewed", fields: ["pay_rate"], from: "203.0.113.9",
        browser: "Chrome" }] },
      [`GET /api/people/${ACME}/`]: page({ level: "director", level_label: "HR Director",
                                          manages: true, may_add: true }),
    });
    await userEvent.click(await screen.findByRole("tab", { name: "Permissions" }));
    expect(await screen.findByText("Two-factor not set up yet")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Access log" }));
    const log = await screen.findByRole("table", { name: "Access log entries" });
    expect(log).toHaveTextContent("Pay rate");
    expect(log).toHaveTextContent("203.0.113.9");
  });
});
