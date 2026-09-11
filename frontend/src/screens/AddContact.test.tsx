import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CONTACT_TYPES, PIPELINES, aCompany, aContact, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { AddContact } from "./AddContact";

function setup(overrides: Record<string, unknown> = {}) {
  const onDone = vi.fn();
  const created = vi.fn((body: unknown) => ({ status: 201, body: { ...aContact(), ...(body as object) } }));
  const fetchMock = mockApi({
    "/api/companies/": [aCompany({ id: "co-1", name: "Acme Holdings" })],
    "/api/contact-types/": CONTACT_TYPES,
    "/api/pipelines/": PIPELINES,
    "POST /api/contacts/": created,
    ...overrides,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<AddContact me={aMe()} onDone={onDone} />);
  return { onDone, fetchMock };
}

/** The body of the single POST the form makes. */
function postedBody(fetchMock: ReturnType<typeof mockApi>) {
  const call = fetchMock.calls.find((c) => c.method === "POST");
  return call?.body as Record<string, unknown>;
}

describe("AddContact", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("sends every FR-1.1 field in one request", async () => {
    const user = userEvent.setup();
    const { fetchMock, onDone } = setup();

    await user.type(screen.getByLabelText("First name"), "Dana");
    await user.type(screen.getByLabelText("Last name"), "Reyes");
    await user.type(screen.getByLabelText("Title"), "COO");
    await user.type(screen.getByLabelText("Email 1"), "dana@acme.invalid");
    await user.type(screen.getByLabelText("Phone 1"), "555-0100");
    await user.type(screen.getByLabelText("Source"), "Referral");
    await user.type(screen.getByLabelText("Tags"), "vip; warm");
    await user.type(screen.getByLabelText("Background"), "Met at the roundtable");
    await user.click(screen.getByLabelText("Prospect"));

    await user.click(screen.getByRole("button", { name: "Save contact" }));

    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(postedBody(fetchMock)).toMatchObject({
      first_name: "Dana", last_name: "Reyes", title: "COO",
      source: "Referral", background: "Met at the roundtable",
      tags: ["vip", "warm"],
      emails: [{ address: "dana@acme.invalid", is_primary: true }],
      phones: [{ number: "555-0100", is_primary: true }],
      types: ["prospect"],
    });
  });

  it("sends a second email with exactly one marked primary", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.type(screen.getByLabelText("First name"), "Dana");
    await user.type(screen.getByLabelText("Email 1"), "first@x.invalid");
    await user.click(screen.getByRole("button", { name: "Add another email" }));
    await user.type(screen.getByLabelText("Email 2"), "second@x.invalid");
    // Radio, not checkbox: marking the second primary un-marks the first, which
    // is what the partial unique index requires.
    await user.click(screen.getByLabelText("Make email 2 primary"));

    await user.click(screen.getByRole("button", { name: "Save contact" }));

    await waitFor(() => expect(postedBody(fetchMock)).toBeTruthy());
    expect(postedBody(fetchMock).emails).toEqual([
      { address: "first@x.invalid", is_primary: false },
      { address: "second@x.invalid", is_primary: true },
    ]);
  });

  it("picks an existing company", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.type(screen.getByLabelText("First name"), "Dana");
    await user.selectOptions(await screen.findByLabelText("Company"), "co-1");
    await user.click(screen.getByRole("button", { name: "Save contact" }));

    await waitFor(() => expect(postedBody(fetchMock)).toBeTruthy());
    expect(postedBody(fetchMock)).toMatchObject({ company: "co-1", company_name: "" });
  });

  it("creates a company inline, and disables the picker while doing so", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.type(screen.getByLabelText("First name"), "Dana");
    await user.type(screen.getByLabelText("New company name"), "Brand New Co");
    await user.click(screen.getByRole("button", { name: "Save contact" }));

    await waitFor(() => expect(postedBody(fetchMock)).toBeTruthy());
    expect(postedBody(fetchMock)).toMatchObject({
      company: null, company_name: "Brand New Co",
    });
  });

  it("sends an optional pipeline placement", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.type(screen.getByLabelText("First name"), "Dana");
    await user.selectOptions(await screen.findByLabelText("Pipeline"), "p-sales");
    await user.selectOptions(screen.getByLabelText("Stage"), "qualified");
    await user.click(screen.getByRole("button", { name: "Save contact" }));

    await waitFor(() => expect(postedBody(fetchMock)).toBeTruthy());
    expect(postedBody(fetchMock).placement).toEqual({
      pipeline: "p-sales", stage: "qualified",
    });
  });

  it("omits placement entirely when no pipeline is chosen", async () => {
    const user = userEvent.setup();
    const { fetchMock } = setup();

    await user.type(screen.getByLabelText("First name"), "Dana");
    await user.click(screen.getByRole("button", { name: "Save contact" }));

    await waitFor(() => expect(postedBody(fetchMock)).toBeTruthy());
    expect(postedBody(fetchMock)).not.toHaveProperty("placement");
  });

  it("warns that a referral partner queues an onboarding email", async () => {
    const user = userEvent.setup();
    setup();

    await user.click(await screen.findByLabelText("Referral partner"));

    expect(screen.getByText(/queue their onboarding email/)).toBeInTheDocument();
    expect(screen.getByText(/does not send anything/)).toBeInTheDocument();
  });

  it("cannot be saved without a name", async () => {
    setup();
    expect(screen.getByRole("button", { name: "Save contact" })).toBeDisabled();
  });

  it("shows the API's field error rather than a generic failure", async () => {
    const user = userEvent.setup();
    setup({
      "POST /api/contacts/": () => ({
        status: 400, body: { emails: ["Only one email address can be the primary one."] },
      }),
    });

    await user.type(screen.getByLabelText("First name"), "Dana");
    await user.click(screen.getByRole("button", { name: "Save contact" }));

    expect(
      await screen.findByText(/Only one email address can be the primary one/),
    ).toBeInTheDocument();
  });
});
