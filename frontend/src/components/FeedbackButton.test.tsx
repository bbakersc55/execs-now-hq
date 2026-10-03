import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { FeedbackButton } from "./FeedbackButton";

describe("the Feedback button (P2 §7)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says where it goes, sends the three answers and the page, and thanks you", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({ "POST /api/feedback/": () => ({ status: 201, body: { id: "1" } }) });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<FeedbackButton />, { path: "/digests", route: "/digests?x=1" });
    await user.click(screen.getByRole("button", { name: "Feedback" }));
    expect(screen.getByText(/go to the platform owner/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
    await user.type(screen.getByLabelText("What were you doing?"), "Approving");
    await user.type(screen.getByLabelText("What happened?"), "Spinner");
    await user.type(screen.getByLabelText("What did you expect?"), "Approved");
    await user.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText(/It's on its way/)).toBeInTheDocument();
    const body = fetchMock.mock.calls[0][1]?.body as FormData;
    expect(Object.fromEntries(body.entries())).toEqual({
      doing: "Approving", happened: "Spinner", expected: "Approved", page_url: "/digests?x=1" });
  });

  it("appears on staff screens and never for a client", async () => {
    const { App } = await import("../App");
    const BRAND = { display_name: "Acme", logo_url: "", mark_url: "/api/branding/mark",
      footer_text: "", palette: { header: "#1F2933", accent: "#7B8794", on_header: "#FFFFFF",
        on_accent: "#1F2933", gray_dark: "#6D6E71", gray_light: "#939598" },
      product_name: null };
    vi.stubGlobal("fetch", mockApi({ "GET /api/me": aMe({ role: "FCC" }),
      "GET /api/branding": BRAND, "GET /api/": [] }));
    renderRoute(<App />, { path: "*", route: "/work" });
    await screen.findAllByText("Our work");
    expect(screen.queryByRole("button", { name: "Feedback" })).toBeNull();
  });

  it("is there for staff", async () => {
    const { App } = await import("../App");
    vi.stubGlobal("fetch", mockApi({ "GET /api/me": aMe({ role: "VA" }),
      "GET /api/branding": { display_name: "Acme", logo_url: "", mark_url: "", footer_text: "",
        palette: null, product_name: "Execs NOW HQ" },
      "GET /api/": [] }));
    renderRoute(<App />, { path: "*", route: "/tasks" });
    expect(await screen.findByRole("button", { name: "Feedback" })).toBeInTheDocument();
  });
});
