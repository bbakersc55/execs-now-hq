import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CONTACT_TYPES, PIPELINES, aCompany, aContact, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { AddCompany } from "./AddCompany";
import { AddContact } from "./AddContact";

function patched(fetchMock: ReturnType<typeof mockApi>) {
  return fetchMock.calls.find((c) => c.method === "PATCH");
}

describe("Edit contact", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const existing = aContact({
    id: "dana", first_name: "Dana", last_name: "Reyes", title: "COO",
    tags: ["vip", "warm"], source: "Referral", background: "Met at the roundtable",
    company: "co-1", type_codes: ["prospect"],
    emails: [
      { id: "e1", address: "dana@acme.invalid", is_primary: true },
      { id: "e2", address: "d.reyes@home.invalid", is_primary: false },
    ],
    phones: [{ id: "p1", number: "555-0100", is_primary: true }],
  });

  function setup(me = aMe()) {
    const onDone = vi.fn();
    const fetchMock = mockApi({
      "/api/companies/": [aCompany({ id: "co-1", name: "Acme Holdings" })],
      "/api/contact-types/": CONTACT_TYPES,
      "/api/pipelines/": PIPELINES,
      "/api/staff/": [{ id: "u-cf", full_name: "Dana CF", email: "cf@x.invalid" }],
      "PATCH /api/contacts/dana/": (body: unknown) => ({ status: 200, body }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<AddContact me={me} existing={existing} onDone={onDone} />);
    return { fetchMock, onDone };
  }

  it("prefills every field from the existing contact", async () => {
    setup();
    expect(await screen.findByText("Edit contact")).toBeInTheDocument();
    expect(screen.getByLabelText("First name")).toHaveValue("Dana");
    expect(screen.getByLabelText("Title")).toHaveValue("COO");
    expect(screen.getByLabelText("Email 1")).toHaveValue("dana@acme.invalid");
    expect(screen.getByLabelText("Email 2")).toHaveValue("d.reyes@home.invalid");
    expect(screen.getByLabelText("Phone 1")).toHaveValue("555-0100");
    expect(screen.getByLabelText("Tags")).toHaveValue("vip, warm");
    expect(screen.getByLabelText("Background")).toHaveValue("Met at the roundtable");
    expect(await screen.findByLabelText("Prospect")).toBeChecked();
    expect(await screen.findByLabelText("Company")).toHaveValue("co-1");
  });

  it("PATCHes rather than creating a second contact", async () => {
    const user = userEvent.setup();
    const { fetchMock, onDone } = setup();

    await user.clear(screen.getByLabelText("Title"));
    await user.type(screen.getByLabelText("Title"), "Chief Operating Officer");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(patched(fetchMock)?.url).toBe("/api/contacts/dana/");
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
    expect(patched(fetchMock)?.body).toMatchObject({ title: "Chief Operating Officer" });
  });

  it("removes an email and re-primaries the other", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.click(screen.getByRole("button", { name: "Remove email 1" }));
    // Only one left, and it becomes the primary.
    await user.click(screen.getByLabelText("Make email 1 primary"));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(patched(fetchMock)).toBeTruthy());
    expect(patched(fetchMock)?.body).toMatchObject({
      emails: [{ address: "d.reyes@home.invalid", is_primary: true }],
    });
  });

  it("adds a phone and keeps exactly one primary", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.click(screen.getByRole("button", { name: "Add another phone" }));
    await user.type(screen.getByLabelText("Phone 2"), "555-0199");
    await user.click(screen.getByLabelText("Make phone 2 primary"));
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(patched(fetchMock)).toBeTruthy());
    expect(patched(fetchMock)?.body).toMatchObject({
      phones: [
        { number: "555-0100", is_primary: false },
        { number: "555-0199", is_primary: true },
      ],
    });
  });

  it("lets an FF reassign the owner", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup(aMe({ role: "FF" }));

    // Wait for the staff list to arrive before choosing from it.
    await screen.findByRole("option", { name: "Dana CF" });
    await user.selectOptions(screen.getByLabelText("Owner"), "u-cf");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(patched(fetchMock)).toBeTruthy());
    expect(patched(fetchMock)?.body).toMatchObject({ owner: "u-cf" });
  });

  it("hides the owner field from a VA and never sends one", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup(aMe({ role: "VA" }));

    expect(screen.queryByLabelText("Owner")).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(patched(fetchMock)).toBeTruthy());
    expect(patched(fetchMock)?.body).not.toHaveProperty("owner");
  });
});

describe("Edit company", () => {
  beforeEach(() => vi.unstubAllGlobals());

  const existing = aCompany({
    id: "co-1", name: "Acme Holdings", industry: "Manufacturing",
    domains: ["acme.com"], address: { lines: ["1 Main St", "Denver"] },
    seat_count: 3,
  });

  function setup(me = aMe()) {
    const onDone = vi.fn();
    const fetchMock = mockApi({
      "PATCH /api/companies/co-1/": (body: unknown) => ({ status: 200, body }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<AddCompany me={me} existing={existing} onDone={onDone} />);
    return { fetchMock, onDone };
  }

  it("prefills and PATCHes", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    expect(screen.getByText("Edit company")).toBeInTheDocument();
    expect(screen.getByLabelText("Name")).toHaveValue("Acme Holdings");
    expect(screen.getByLabelText("Email domains")).toHaveValue("acme.com");
    expect(screen.getByLabelText("Address")).toHaveValue("1 Main St\nDenver");
    expect(screen.getByLabelText("Client seat count")).toHaveValue(3);

    await user.type(screen.getByLabelText("Industry"), " and Logistics");
    await user.click(screen.getByRole("button", { name: "Save changes" }));

    await waitFor(() => expect(patched(fetchMock)).toBeTruthy());
    expect(patched(fetchMock)?.url).toBe("/api/companies/co-1/");
    expect(patched(fetchMock)?.body).toMatchObject({
      industry: "Manufacturing and Logistics",
    });
  });

  it("still never offers the client flag", () => {
    setup();
    expect(screen.queryByLabelText(/client company/i)).not.toBeInTheDocument();
  });
});
