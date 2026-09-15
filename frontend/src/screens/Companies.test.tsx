import { screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aCompany, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Companies } from "./Companies";

describe("Companies list: seat usage (matrix 9.5)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows seats in use to the FF", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/companies/": [aCompany()] }));
    renderRoute(<Companies me={aMe()} />);
    expect(await screen.findByText("Adapt CFO")).toBeInTheDocument();
    expect(screen.getByRole("columnheader", { name: "Seats" })).toBeInTheDocument();
    expect(screen.getByText("2 / 3")).toBeInTheDocument();
  });

  it("shows a VA no seats column, even if a stale payload still carried usage", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/companies/": [aCompany()] }));
    renderRoute(<Companies me={aMe({ role: "VA" })} />);
    expect(await screen.findByText("Adapt CFO")).toBeInTheDocument();
    expect(screen.queryByRole("columnheader", { name: "Seats" })).not.toBeInTheDocument();
    expect(screen.queryByText("2 / 3")).not.toBeInTheDocument();
  });
});
