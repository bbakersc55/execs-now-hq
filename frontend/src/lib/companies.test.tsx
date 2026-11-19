import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LinkPicker } from "../components/LinkPicker";
import { aCompany } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { CompanyOptions, companyName, isClientCompany, practiceThenClients, sortCompanies } from "./companies";

/** Bryan, 2026-11-18: one order for every company list. */
const MIXED = [
  { id: "1", name: "zeta Vendor", is_client_company: false },
  { id: "2", name: "Beacon Labs", is_client_company: true },
  { id: "3", name: "acme Plumbing", is_client_company: false },
  { id: "4", name: "alpine Stay Co.", is_client_company: true },
  { id: "5", name: "Acorn Supply", is_client_company: false },
];

describe("the company order (2026-11-18)", () => {
  it("puts clients first, each group alphabetical, upper and lower case alike", () => {
    expect(sortCompanies(MIXED, companyName, isClientCompany).map((c) => c.name)).toEqual([
      "alpine Stay Co.", "Beacon Labs", "acme Plumbing", "Acorn Supply", "zeta Vendor"]);
  });

  it("is simply alphabetical for a list of clients", () => {
    expect(sortCompanies([{ name: "beta" }, { name: "Alpha" }, { name: "gamma" }], companyName)
      .map((c) => c.name)).toEqual(["Alpha", "beta", "gamma"]);
  });

  it("keeps the practice's own first, then its clients alphabetically", () => {
    expect(practiceThenClients([{ name: "zeta", is_practice: false },
      { name: "Executives Now", is_practice: true }, { name: "Acme", is_practice: false }])
      .map((c) => c.name)).toEqual(["Executives Now", "Acme", "zeta"]);
  });

  it("labels the two groups of a mixed drop-down, and leaves a list of clients plain", () => {
    const { rerender } = render(
      <select aria-label="Company">
        <option value="">Any company</option>
        <CompanyOptions items={MIXED} id={(c) => c.id} name={companyName} isClient={isClientCompany} />
      </select>);
    const groups = screen.getAllByRole("group");
    expect(groups.map((g) => g.getAttribute("label"))).toEqual(["Clients", "Other companies"]);
    expect(within(groups[0]).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["alpine Stay Co.", "Beacon Labs"]);
    expect(within(groups[1]).getAllByRole("option").map((o) => o.textContent))
      .toEqual(["acme Plumbing", "Acorn Supply", "zeta Vendor"]);
    // "Any company" stays first, outside the groups.
    expect(screen.getAllByRole("option")[0]).toHaveTextContent("Any company");

    rerender(
      <select aria-label="Company">
        <CompanyOptions items={MIXED.filter((c) => c.is_client_company)} id={(c) => c.id}
          name={companyName} isClient={isClientCompany} />
      </select>);
    expect(screen.queryAllByRole("group")).toEqual([]);
    expect(screen.getAllByRole("option").map((o) => o.textContent))
      .toEqual(["alpine Stay Co.", "Beacon Labs"]);
  });
});

describe("a company picker on a screen", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("lists clients first under their label in the note's link picker", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "GET /api/companies/": MIXED.map((c) => aCompany(c)),
      "GET /api/tasks/": [],
    }));
    renderRoute(<LinkPicker value={{ contact: null, company: null, task: null }}
      onChange={() => {}} />);
    await user.click(screen.getByLabelText("A company"));
    const select = await screen.findByLabelText("Company");
    await within(select).findByRole("group", { name: "Clients" });
    expect(within(select).getAllByRole("option").map((o) => o.textContent)).toEqual([
      "Choose a company…", "alpine Stay Co.", "Beacon Labs", "acme Plumbing", "Acorn Supply",
      "zeta Vendor"]);
  });
});
