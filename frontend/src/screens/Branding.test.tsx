import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi, renderRoute } from "../test/render";
import { Branding, BrandingSettings } from "./Branding";

const UNSET: BrandingSettings = {
  display_name: "", practice_name: "Acme Advisory LLC",
  primary_color: "#1F2933", accent_color: "#7B8794", footer_text: "",
  has_logo: false, has_mark: false, branding_updated_at: null,
  defaults: { primary_color: "#1F2933", accent_color: "#7B8794" },
};

function show(settings: BrandingSettings = UNSET, extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    ...extra,
    "GET /api/settings/branding": settings,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Branding />);
  return fetchMock;
}

async function setColor(label: string, value: string) {
  const user = userEvent.setup();
  const input = await screen.findByLabelText(label);
  await user.clear(input);
  await user.type(input, value);
}

describe("Settings → Branding (P1)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says an unset practice shows its name over neutral grays, and previews it", async () => {
    show();
    expect(await screen.findByText(/Not set yet/)).toBeInTheDocument();
    const portal = screen.getByLabelText("Portal preview");
    expect(within(portal).getByText("Acme Advisory LLC")).toBeInTheDocument();
    expect(screen.getAllByText("Passes")).toHaveLength(3);
    expect(screen.getByLabelText("Tab preview").querySelector("img"))
      .toHaveAttribute("src", "/api/branding/mark?v=0");
  });

  it("saves Executives Now's colors with the orange marked decoration only", async () => {
    const user = userEvent.setup();
    const fetchMock = show(UNSET, {
      "PUT /api/settings/branding": (body: unknown) => ({ body: { ...UNSET, ...(body as object),
        branding_updated_at: "2026-10-02T20:00:00Z" } }),
    });
    await screen.findByText(/Not set yet/);
    await user.type(screen.getByLabelText("Display name"), "Executives Now");
    await setColor("Primary color", "#0A3A65");
    await setColor("Accent color", "#F58220");
    expect(screen.getByText("Decoration only")).toBeInTheDocument();
    expect(screen.getByText(/2\.59 : 1/)).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(await screen.findByText(/Branding saved/)).toBeInTheDocument();
    const put = fetchMock.calls.find((c) => c.method === "PUT");
    expect(put?.body).toEqual({ display_name: "Executives Now", primary_color: "#0A3A65",
      accent_color: "#F58220", footer_text: "" });
  });

  it("will not save a primary color white text cannot be read on", async () => {
    show();
    await screen.findByText(/Not set yet/);
    await setColor("Primary color", "#7FB3E0");
    expect(screen.getAllByText("Too low").length).toBeGreaterThan(0);
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText(/would be hard to read/)).toBeInTheDocument();
  });

  it("previews the footer and refuses a seventh line", async () => {
    const user = userEvent.setup();
    show();
    await screen.findByText(/Not set yet/);
    const footer = screen.getByLabelText("Email footer");
    await user.type(footer, "12 Main St{enter}acme.example");
    expect(within(screen.getByLabelText("Footer preview")).getByText(/12 Main St/))
      .toBeInTheDocument();
    expect(screen.getByText(/2 of 6 lines/)).toBeInTheDocument();
    await user.type(footer, "{enter}a{enter}b{enter}c{enter}d{enter}e");
    expect(screen.getByText(/7 of 6 lines/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("uploads a mark and shows the server's refusal in its own words", async () => {
    const user = userEvent.setup();
    const fetchMock = show(UNSET, {
      "POST /api/settings/branding/mark": () => ({
        status: 400, body: { detail: "The mark must be square; this one is 128 x 96 px." } }),
    });
    await screen.findByText(/Not set yet/);
    const file = new File([new Uint8Array([137, 80, 78, 71])], "mark.png", { type: "image/png" });
    await user.upload(screen.getByLabelText("Upload mark"), file);
    expect(await screen.findByText(/must be square/)).toBeInTheDocument();
    await waitFor(() => expect(fetchMock.calls.some((c) =>
      c.method === "POST" && c.url === "/api/settings/branding/mark")).toBe(true));
  });
});
