import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Settings } from "../screens/Settings";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { AgreementGate } from "./AgreementGate";
import { GettingStarted } from "./GettingStarted";

const TEXT = "# Execs NOW HQ Beta Agreement\n\nIntro line.\n\n1. Work in progress. Things change.\n\n"
  + "2. Your data is yours. Whoever operates the servers can technically read the database.";

describe("the beta agreement (P2)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows the text and accepts exactly that version and hash", async () => {
    const user = userEvent.setup();
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const fetchMock = mockApi({
      "GET /api/agreement": { version: "v1", text: TEXT, sha256: "abc", required: true },
      "POST /api/agreement": { accepted: true },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<AgreementGate />);
    expect(await screen.findByRole("heading", { name: "Execs NOW HQ Beta Agreement" }))
      .toBeInTheDocument();
    expect(within(screen.getByLabelText("Beta agreement"))
      .getByText(/Whoever operates the servers/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "I accept" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body)
      .toEqual({ version: "v1", sha256: "abc" });
  });
});

describe("Getting started (P2)", () => {
  beforeEach(() => vi.unstubAllGlobals());
  const SHOWN = { hidden: false, never: false, hidden_until: null };
  const ITEMS = [
    { key: "branding", label: "Set your branding", to: "/settings/branding", done: true },
    { key: "gmail", label: "Connect Gmail", to: "/settings/email", done: false },
    { key: "staff", label: "Invite your team", to: "/staff", done: false }];

  it("links each open item and greys out what is done", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/getting-started/card": SHOWN,
                                     "GET /api/getting-started": ITEMS.slice(0, 2) }));
    renderRoute(<GettingStarted />);
    expect(await screen.findByText("Getting started · 1 of 2 done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect Gmail" }))
      .toHaveAttribute("href", "/settings/email");
    expect(screen.queryByRole("link", { name: "Set your branding" })).toBeNull();
  });

  it("goes away when everything is done", async () => {
    const fetchMock = mockApi({ "GET /api/getting-started/card": SHOWN,
                                "GET /api/getting-started": [ITEMS[0]] });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderRoute(<GettingStarted />);
    await waitFor(() => expect(fetchMock.calls.length).toBe(2));
    expect(container.textContent).toBe("");
  });

  it.each([["Hide for now", "later"], ["Don't show again", "never"]])(
    "is put away by “%s”, for this person", async (button, how) => {
      const fetchMock = mockApi({
        "POST /api/getting-started/card": () => ({ body: { ...SHOWN, hidden: true } }),
        "GET /api/getting-started/card": SHOWN, "GET /api/getting-started": ITEMS });
      vi.stubGlobal("fetch", fetchMock);
      const { container } = renderRoute(<GettingStarted />);
      await userEvent.click(await screen.findByRole("button", { name: button }));
      await waitFor(() => expect(container.textContent).toBe(""));
      expect(fetchMock.calls.filter((c) => c.method === "POST").map((c) => c.body))
        .toEqual([{ how }]);
    });

  it("stays away for someone who put it away", async () => {
    const fetchMock = mockApi({
      "GET /api/getting-started/card": { hidden: true, never: true, hidden_until: null },
      "GET /api/getting-started": ITEMS });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderRoute(<GettingStarted />);
    await waitFor(() => expect(fetchMock.calls.length).toBe(2));
    expect(container.textContent).toBe("");
  });
});

describe("Setup still to do, at the top of Settings", () => {
  beforeEach(() => vi.unstubAllGlobals());
  const ITEMS = [
    { key: "branding", label: "Set your branding", to: "/settings/branding", done: true },
    { key: "gmail", label: "Choose your practice address and connect Gmail",
      to: "/settings/email", done: false },
    { key: "staff", label: "Invite your team", to: "/staff", done: false }];

  it("lists what is undone, linked, whatever was done with the dashboard's card",
    async () => {
      // The card says "never"; Settings does not ask it.
      const fetchMock = mockApi({
        "GET /api/getting-started/card": { hidden: true, never: true, hidden_until: null },
        "GET /api/getting-started": ITEMS });
      vi.stubGlobal("fetch", fetchMock);
      renderRoute(<Settings me={aMe()}><p>The section</p></Settings>,
                  { path: "/settings/email", route: "/settings/email" });
      const banner = await screen.findByRole("region", { name: "Setup still to do" });
      expect(banner).toHaveTextContent("Setup still to do: Choose your practice address and "
        + "connect Gmail · Invite your team");
      expect(within(banner).getByRole("link", { name: /connect Gmail/ }))
        .toHaveAttribute("href", "/settings/email");
      expect(within(banner).queryByText("Set your branding")).toBeNull();
      expect(screen.getByText("The section")).toBeInTheDocument();
      expect(fetchMock.calls.map((c) => c.url)).toEqual(["/api/getting-started"]);
    });

  it("is gone once everything is done", async () => {
    const fetchMock = mockApi({ "GET /api/getting-started": [ITEMS[0]] });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Settings me={aMe()}><p>The section</p></Settings>,
                { path: "/settings/email", route: "/settings/email" });
    await waitFor(() => expect(fetchMock.calls.length).toBe(1));
    expect(screen.queryByRole("region", { name: "Setup still to do" })).toBeNull();
  });

  it("is the practice owner's: an associate's Settings asks for no checklist", async () => {
    const fetchMock = mockApi({});
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<Settings me={aMe({ role: "CF" })}><p>The section</p></Settings>,
                { path: "/settings/email", route: "/settings/email" });
    expect(await screen.findByText("The section")).toBeInTheDocument();
    expect(fetchMock.calls).toEqual([]);
  });
});
