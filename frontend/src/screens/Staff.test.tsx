import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Staff } from "./Staff";

describe("the staff screen", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("suggests an address at the inviter's own domain, not Executives Now's", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/staff/": [] }));
    renderRoute(<Staff me={aMe({ role: "FF", email: "shawn@blueskybizconsulting.com" })} />);
    expect(await screen.findByPlaceholderText("name@blueskybizconsulting.com"))
      .toBeInTheDocument();
    expect(screen.queryByPlaceholderText(/getexecutivesnow/)).toBeNull();
  });

  it("names the roles in its pickers", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/staff/": [] }));
    renderRoute(<Staff me={aMe({ role: "FF" })} />);
    expect(await screen.findByRole("option", { name: "Assistant" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Associate" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Practice owner" })).toBeInTheDocument();
  });
});
