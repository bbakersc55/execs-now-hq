import { screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";

/** P1: the portal wears the practice's colors and mark; staff keep the
 *  product's look and see which practice they are in. */

const BRAND = {
  display_name: "Blue Sky Business Consulting", product_name: "Execs NOW HQ",
  logo_url: "", mark_url: "/api/branding/mark", footer_text: "",
  palette: { header: "#2E7D32", accent: "#F9A825", on_header: "#FFFFFF",
             on_accent: "#1F2933", gray_dark: "#6D6E71", gray_light: "#939598" },
};

function stubApp(role: "FF" | "FCC") {
  vi.stubGlobal("fetch", mockApi({
    "GET /api/me": aMe({ role }),
    "GET /api/branding": role === "FF" ? BRAND : { ...BRAND, product_name: null },
    "GET /api/": [],
  }));
}

const token = (name: string) => document.documentElement.style.getPropertyValue(name);
const icon = () => document.querySelector("link[rel='icon']")?.getAttribute("href");

describe("branding in the shell (P1)", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.removeAttribute("style");
    document.head.querySelectorAll("link[rel='icon']").forEach((l) => l.remove());
  });

  it("gives a client the practice's whole color family, mark and name", async () => {
    const { App } = await import("../App");
    stubApp("FCC");
    renderRoute(<App />, { path: "*", route: "/work" });
    await waitFor(() => expect(token("--navy")).toBe("#2E7D32"));
    expect(token("--orange")).toBe("#F9A825");
    expect(token("--on-orange")).toBe("#1F2933");
    expect(token("--navy-300")).toMatch(/^#[0-9a-f]{6}$/);
    expect(icon()).toBe("/api/branding/mark");
    expect(document.title).toBe("Blue Sky Business Consulting");
    expect(document.body.textContent).not.toMatch(/Execs NOW HQ/);
  });

  it("keeps staff on the product's look, with the practice named under it", async () => {
    const { App } = await import("../App");
    stubApp("FF");
    renderRoute(<App />, { path: "*", route: "/tasks" });
    expect(await screen.findByLabelText("Practice"))
      .toHaveTextContent("Blue Sky Business Consulting");
    expect(screen.getByRole("heading", { name: "Execs NOW HQ" })).toBeInTheDocument();
    await waitFor(() => expect(icon()).toMatch(/brand\/favicon-32\.png$/));
    expect(token("--navy")).toBe("");
    expect(token("--orange")).toBe("");
    expect(document.title).toBe("Execs NOW HQ");
  });
});
