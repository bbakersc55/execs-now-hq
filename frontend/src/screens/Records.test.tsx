import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aCompany, aContact, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Companies } from "./Companies";
import { Contacts } from "./Contacts";

const DANA = aContact({
  id: "c1", first_name: "Dana", last_name: "Reyes", title: "COO",
  emails: [{ id: "e1", address: "dana@acme.invalid", is_primary: true }],
  type_codes: ["client"],
});
const ADA = aContact({
  id: "c2", first_name: "Ada", last_name: "Nwosu", title: "",
  emails: [{ id: "e2", address: "ada@northwind.invalid", is_primary: true }],
  type_codes: ["prospect"], pipeline_positions: [],
});

function showContacts(rows = [DANA, ADA], extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "GET /api/contacts/search/": { contacts: rows, companies: [], notes: [] },
    "GET /api/contacts/": rows,
    "GET /api/contact-types/": [{ code: "client", label: "Client" },
                                { code: "prospect", label: "Prospect" }],
    "GET /api/pipelines/": [],
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Contacts me={aMe()} />, { path: "/contacts", route: "/contacts" });
  return fetchMock;
}

/** The names as read, ignoring the avatar's initials beside them. */
function names() {
  return screen.getAllByRole("row").slice(1)
    .map((row) => within(row).getAllByRole("link")[0].textContent);
}

/**
 * Contacts and Companies (design brief, Tier 2).
 *
 * **Tables stay, because these are records** — compared across rows, which a
 * grid of cards makes impossible. Everything the pass adds is what goes
 * *around* the table.
 */
describe("the contacts list", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("searches as you type, with no Search button to press", async () => {
    const user = userEvent.setup();
    const fetchMock = showContacts();
    await screen.findByText("COO");

    expect(screen.queryByRole("button", { name: "Search" })).not.toBeInTheDocument();
    await user.type(screen.getByRole("searchbox", { name: "Search contacts" }), "dana");

    // Debounced: five keystrokes are one request, not five.
    await vi.waitFor(() => expect(
      fetchMock.calls.filter((c) => c.url.includes("/search/")).length).toBe(1));
    expect(fetchMock.calls.at(-1)!.url).toContain("q=dana");
  });

  it("says what is narrowing the list, and clears it in one click", async () => {
    const user = userEvent.setup();
    showContacts();
    await screen.findByText("COO");

    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by type" }),
                             "client");

    // Chips, not bare dropdowns: what is being filtered is stated.
    expect(await screen.findByText("Type: Client")).toBeInTheDocument();
    expect(names()).toEqual(["Dana Reyes"]);

    await user.click(screen.getByRole("button", { name: /Clear filter Type: Client/ }));
    expect(names()).toHaveLength(2);
  });

  it("sorts by a column, and says so to a screen reader", async () => {
    const user = userEvent.setup();
    showContacts();
    await screen.findByText("COO");

    // Default is by surname: Nwosu before Reyes.
    expect(names()).toEqual(["Ada Nwosu", "Dana Reyes"]);

    const header = screen.getByRole("columnheader", { name: "Name" });
    expect(header).toHaveAttribute("aria-sort", "ascending");
    await user.click(within(header).getByRole("button"));

    expect(names()).toEqual(["Dana Reyes", "Ada Nwosu"]);
    expect(screen.getByRole("columnheader", { name: "Name" }))
      .toHaveAttribute("aria-sort", "descending");
  });

  it("sorts blanks last in both directions", async () => {
    const user = userEvent.setup();
    showContacts();
    await screen.findByText("COO");

    const title = screen.getByRole("columnheader", { name: "Title" });
    await user.click(within(title).getByRole("button"));
    // Ada has no title. An empty cell is absent information, not a low value.
    expect(names()).toEqual(["Dana Reyes", "Ada Nwosu"]);
    await user.click(within(title).getByRole("button"));
    expect(names()).toEqual(["Dana Reyes", "Ada Nwosu"]);
  });

  it("peeks at a row before committing to the whole record", async () => {
    const user = userEvent.setup();
    showContacts();
    await screen.findByText("COO");

    await user.click(screen.getByRole("button", { name: "Peek at Dana Reyes" }));

    const sheet = await screen.findByRole("dialog", { name: "Contact" });
    expect(within(sheet).getByText("dana@acme.invalid")).toBeInTheDocument();
    // A look, not the record — and a way to get to the record.
    expect(within(sheet).getByRole("link", { name: /Open the full record/ }))
      .toHaveAttribute("href", "/contacts/c1");

    await user.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("still selects and bulk-drafts behind a filter", async () => {
    const user = userEvent.setup();
    const fetchMock = showContacts([DANA, ADA], {
      "POST /api/contacts/draft-touches/": { drafted_count: 1, skipped: [] },
    });
    await screen.findByText("COO");

    await user.selectOptions(screen.getByRole("combobox", { name: "Filter by type" }),
                             "client");
    await user.click(screen.getByRole("button", { name: /Select all/ }));
    await user.click(screen.getByRole("button", { name: "Draft touch now" }));

    // Selecting behind a filter you cannot see is how people mail the wrong
    // list — so the filter narrows what "select all" means, and it still does.
    await vi.waitFor(() => {
      const posted = fetchMock.calls.find((c) => c.url.endsWith("/draft-touches/"));
      expect(posted?.body).toEqual({ ids: ["c1"] });
    });
  });
});

describe("the companies list", () => {
  beforeEach(() => vi.unstubAllGlobals());

  function showCompanies(rows = [
    aCompany({ id: "co1", name: "Acme Facilities", industry: "Facilities" }),
    aCompany({ id: "co2", name: "Northwind", industry: "",
               is_client_company: false, seat_count: null }),
  ]) {
    vi.stubGlobal("fetch", mockApi({ "GET /api/companies/": rows }));
    renderRoute(<Companies me={aMe()} />, { path: "/companies", route: "/companies" });
  }

  it("filters to clients only, and says that is what it is doing", async () => {
    const user = userEvent.setup();
    showCompanies();
    await screen.findByText("Acme Facilities");

    await user.click(screen.getByRole("checkbox", { name: /Clients only/ }));

    // The chip, not the checkbox label — what is narrowing the list is stated
    // where the list is, and clearing it is one click.
    expect(await screen.findByRole("button",
                                   { name: /Clear filter Clients only/ }))
      .toBeInTheDocument();
    expect(screen.queryByText("Northwind")).not.toBeInTheDocument();
  });

  it("searches instantly across name and industry", async () => {
    const user = userEvent.setup();
    showCompanies();
    await screen.findByText("Acme Facilities");

    await user.type(screen.getByRole("searchbox", { name: "Search companies" }),
                    "northw");

    await vi.waitFor(() =>
      expect(screen.queryByText("Acme Facilities")).not.toBeInTheDocument());
    expect(screen.getByText("Northwind")).toBeInTheDocument();
  });

  it("peeks before committing to the whole record", async () => {
    const user = userEvent.setup();
    showCompanies();
    await screen.findByText("Acme Facilities");

    await user.click(screen.getByRole("button", { name: "Peek at Acme Facilities" }));

    const sheet = await screen.findByRole("dialog", { name: "Company" });
    expect(within(sheet).getByText(/of 3 in use/)).toBeInTheDocument();
    expect(within(sheet).getByRole("link", { name: /Open the full record/ }))
      .toHaveAttribute("href", "/companies/co1");
  });

  it("keeps seat usage out of a VA's peek too", async () => {
    /* Matrix 9.5. The peek is a new surface, and a rule that holds on the
       table has to hold on every other place the same number appears. */
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "GET /api/companies/": [aCompany({ id: "co1", name: "Acme Facilities" })] }));
    renderRoute(<Companies me={aMe({ role: "VA" })} />,
                { path: "/companies", route: "/companies" });
    await screen.findByText("Acme Facilities");

    await user.click(screen.getByRole("button", { name: "Peek at Acme Facilities" }));

    const sheet = await screen.findByRole("dialog", { name: "Company" });
    expect(within(sheet).queryByText(/in use/)).not.toBeInTheDocument();
    expect(within(sheet).queryByText("Seats")).not.toBeInTheDocument();
  });

  it("says when filters match nothing, differently from having nothing", async () => {
    const user = userEvent.setup();
    showCompanies();
    await screen.findByText("Acme Facilities");

    await user.type(screen.getByRole("searchbox", { name: "Search companies" }), "zzz");

    expect(await screen.findByText("No companies match those filters."))
      .toBeInTheDocument();
  });
});
