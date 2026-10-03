import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

  it("links each open item and greys out what is done", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/getting-started": [
      { key: "branding", label: "Set your branding", to: "/settings/branding", done: true },
      { key: "gmail", label: "Connect Gmail", to: "/settings/email", done: false },
    ] }));
    renderRoute(<GettingStarted />);
    expect(await screen.findByText("Getting started · 1 of 2 done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Connect Gmail" }))
      .toHaveAttribute("href", "/settings/email");
    expect(screen.queryByRole("link", { name: "Set your branding" })).toBeNull();
  });

  it("goes away when everything is done", async () => {
    const fetchMock = mockApi({ "GET /api/getting-started": [
      { key: "branding", label: "Set your branding", to: "/settings/branding", done: true },
    ] });
    vi.stubGlobal("fetch", fetchMock);
    const { container } = renderRoute(<GettingStarted />);
    await waitFor(() => expect(fetchMock.calls.length).toBe(1));
    expect(container.textContent).toBe("");
  });
});
