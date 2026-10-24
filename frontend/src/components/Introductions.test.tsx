import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { IntroductionsCard, WhatTheyDo } from "./Introductions";
import { aContact, aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Contacts } from "../screens/Contacts";

const MAYA = aContact({ id: "maya", first_name: "Maya", last_name: "Chen", type_codes: ["referral_partner"],
  discipline: "cmo", discipline_label: "Fractional CMO", specialties: ["Go to market"] });
const DANA = aContact({ id: "dana", first_name: "Dana", last_name: "Reyes", type_codes: ["prospect"],
  emails: [{ id: "e2", address: "dana@x.invalid", is_primary: true }] });
const INTRO = { id: "i1", on: "2026-10-24", note: "Both in logistics.", made_by: "Bryan Baker",
  partner: { id: "maya", name: "Maya Chen", company: "", discipline: "Fractional CMO" },
  to: { id: "dana", name: "Dana Reyes", company: "Acme", discipline: "" },
  outcome: "", outcome_label: "", draft_state: "pending_approval" };

describe("introductions (R3)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("introduces a partner to someone, drafting to both, and counts them", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/introductions/": { ...INTRO, drafts: 2 },
      "PATCH /api/introductions/i1/": { ...INTRO, outcome: "client" },
      "/api/introductions/": { introductions: [INTRO], counts: { made: 1, became_client: 0 },
        counts_text: "1 introduction made · 0 became a client" },
      "/api/contacts/": [MAYA, DANA],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<IntroductionsCard contact={MAYA} partner />);
    expect(await screen.findByText("1 introduction made · 0 became a client")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Dana Reyes" })).toBeInTheDocument();
    await user.selectOptions(screen.getByLabelText("How the introduction to Dana Reyes went"), "client");
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body).toEqual({ outcome: "client" }));
    await user.click(screen.getByRole("button", { name: "Introduce to…" }));
    await user.type(screen.getByLabelText("Introduce to"), "dana");
    await user.click(await screen.findByRole("option", { name: /Dana Reyes/ }));
    await user.type(screen.getByLabelText("Why you're introducing them"), "Both in logistics.");
    await user.click(screen.getByRole("button", { name: "Draft the introduction" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual(
      { partner: "maya", to: "dana", note: "Both in logistics." }));
    expect(await screen.findByRole("status")).toHaveTextContent("A draft to each of Maya and Dana Reyes");
  });

  it("isn't shown on a non-partner's page with none", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/introductions/": { introductions: [], counts: { made: 0, became_client: 0 }, counts_text: "" } }));
    renderRoute(<IntroductionsCard contact={DANA} partner={false} />);
    await waitFor(() => expect(screen.queryByText("Introductions")).toBeNull());
  });

  it("sets what a partner does: a discipline and specialty chips", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PATCH /api/contacts/maya/": MAYA,
      "/api/contacts/specialties/": [{ specialty: "Social media ads", contacts: 2 }],
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<WhatTheyDo contact={MAYA} />);
    expect(screen.getByText("Fractional CMO")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Change" }));
    await user.type(screen.getByLabelText("Specialties"), "Social media ads{Enter}");
    await user.click(screen.getByRole("button", { name: "Remove Go to market" }));
    await user.selectOptions(screen.getByLabelText("Discipline"), "coo");
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body).toEqual(
      { discipline: "coo", specialties: ["Social media ads"] }));
  });
});

describe("finding a partner by what they do (R3b)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("filters Contacts by discipline and by specialty", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("fetch", mockApi({
      "/api/contacts/specialties/": [{ specialty: "Go to market", contacts: 1 }],
      "/api/contacts/": [MAYA, DANA], "/api/contact-types/": [], "/api/pipelines/": [],
      "/api/email-templates/": [],
    }));
    renderRoute(<Contacts me={aMe()} />);
    expect((await screen.findAllByText(/Dana/)).length).toBeGreaterThan(0);
    await user.selectOptions(await screen.findByLabelText("Filter by specialty"), "Go to market");
    await waitFor(() => expect(screen.queryByText(/Dana/)).toBeNull());
    expect(screen.getAllByText(/Maya/).length).toBeGreaterThan(0);
    await user.click(screen.getByRole("button", { name: /Clear all/i }));
    await user.selectOptions(screen.getByLabelText("Filter by discipline"), "cfo");
    await waitFor(() => expect(screen.queryByText(/Maya/)).toBeNull());
    expect(within(document.body).queryByText(/Dana/)).toBeNull();
  });
});
