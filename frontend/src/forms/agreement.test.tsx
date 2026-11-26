/** The owner's agreement pages (docs/p15_owner_agreements.md): the address,
 *  the welcome, the terms shown plainly, signing only with consent and a
 *  signature, and onboarding now or later. */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { mockApi } from "../test/render";
import { AgreementApp } from "./AgreementApp";
import type { AgreementPage } from "./agreementApi";
import { isAgreement, tokenFrom } from "./token";
import type { Brand } from "./types";

const BRAND: Brand = { brand_name: "Mountain Stays", title: "Rental Management Agreement",
  slug: "mountain-stays", colors: {}, contact_phone: "435-555-0100", contact_email: "",
  logo: "", icon: "" };
const TOKEN = "a".repeat(43);
const BASE = `/api/fa/${TOKEN}`;

function page(over: Partial<AgreementPage> = {}): AgreementPage {
  return {
    state: "open", role: "first", position: 1,
    owners: [{ position: 1, name: "Alex Sample", signed: false }], waiting_for: "",
    all_signed: false, number: 4, title: "Rental Management Agreement",
    brand_name: "Mountain Stays", first_name: "Alex",
    blocks: [
      { type: "title", text: "SKYRUN PARK CITY" },
      { type: "para", indent: 0, spans: [{ t: "bold", v: "15) COMMISSION SPLIT:" },
        { t: "text", v: " Owner shall receive " }, { t: "term", k: "owner_percent", v: "72.5" },
        { t: "text", v: "% of the rental revenue" }] },
      { type: "section_30", paras: ["None."] },
    ],
    terms: { owner_percent: "72.5", manager_percent: "27.5", section_30: ["None."],
             property_address: "400 Lift Road, Park City, UT 84060" },
    staff_address: { street: "400 Lift Road", city: "Park City", state: "UT", zip: "84060" },
    details: { first_name: "Alex", last_name: "Sample", email: "alex@samplehomes.net" },
    prefill: { name: "Alex Sample", email: "alex@samplehomes.net", phone: "" },
    missing: [], consent: "By signing electronically, I agree…",
    signed_at: null, countersigned_at: null, onboarding_choice: "", has_pdf: false,
    signer_name: "Michael LeClerc", ...over,
  };
}

beforeEach(() => { window.scrollTo = vi.fn() as unknown as typeof window.scrollTo; });
afterEach(() => vi.unstubAllGlobals());

describe("the owner's agreement", () => {
  it("knows an agreement's address from an intake's", () => {
    expect(isAgreement(`/a/${TOKEN}`)).toBe(true);
    expect(isAgreement(`/forms/mountain-stays/a/${TOKEN}`)).toBe(true);
    expect(isAgreement(`/${TOKEN}`)).toBe(false);
    expect(tokenFrom(`/forms/mountain-stays/a/${TOKEN}`)).toBe(TOKEN);
  });

  it("welcomes the owner, then shows the terms set for them, highlighted", async () => {
    vi.stubGlobal("fetch", mockApi({ [`GET ${BASE}`]: page() }));
    render(<AgreementApp brand={BRAND} token={TOKEN} />);
    expect(await screen.findByText("Welcome, Alex!")).toBeInTheDocument();
    expect(screen.getByText(/trusting your property to the care of the Mountain Stays team/))
      .toBeInTheDocument();
    expect(screen.getByText(/congratulations on your decision to rent it/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Fill in your details" }));
    fireEvent.click(await screen.findByRole("button", { name: "Read the agreement" }));
    const terms = await screen.findByRole("region", { name: "Your terms" });
    expect(terms).toHaveTextContent("You receive 72.5% of rental revenue");
    expect(terms).toHaveTextContent("Mountain Stays receives 27.5%");
    expect(screen.getAllByText("72.5")[0].tagName).toBe("MARK");
  });

  it("signs only with consent and a signature, then offers onboarding", async () => {
    const api = mockApi({
      [`GET ${BASE}`]: page(),
      [`PATCH ${BASE}/details`]: { details: page().details, missing: [], blocks: page().blocks },
      [`POST ${BASE}/sign`]: page({ state: "signed", signed_at: "2026-11-24T17:00:00Z",
                                    has_pdf: true, all_signed: true,
                                    owners: [{ position: 1, name: "Alex Sample",
                                               signed: true }] }),
      [`POST ${BASE}/onboarding`]: { link: "https://forms.example/xyz", choice: "later" },
    });
    vi.stubGlobal("fetch", api);
    render(<AgreementApp brand={BRAND} token={TOKEN} />);
    await screen.findByText("Welcome, Alex!");
    fireEvent.click(screen.getByRole("button", { name: "Fill in your details" }));
    fireEvent.click(await screen.findByRole("button", { name: "Read the agreement" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to sign" }));
    const sign = await screen.findByRole("button", { name: "Sign the agreement" });
    expect(sign).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Your name, as your signature"),
                     { target: { value: "Alex Sample" } });
    expect(sign).toBeDisabled();                                  // no consent yet
    fireEvent.click(screen.getByLabelText("I agree to sign electronically"));
    expect(sign).toBeEnabled();
    fireEvent.click(sign);
    expect(await screen.findByText("Thank you for signing!")).toBeInTheDocument();
    const sent = api.calls.find((c) => c.url.endsWith("/sign"))!;
    expect(sent.body).toEqual({ method: "typed", typed: "Alex Sample", drawn: "",
                                agreed: true });
    fireEvent.click(screen.getByRole("button", { name: "Later: email me the link" }));
    await waitFor(() => expect(screen.getByText(/We've emailed you the link/))
      .toBeInTheDocument());
  });

  it("says what's missing before signing", async () => {
    vi.stubGlobal("fetch", mockApi({ [`GET ${BASE}`]: page({ missing: ["a phone number"] }) }));
    render(<AgreementApp brand={BRAND} token={TOKEN} />);
    await screen.findByText("Welcome, Alex!");
    fireEvent.click(screen.getByRole("button", { name: "Fill in your details" }));
    fireEvent.click(await screen.findByRole("button", { name: "Read the agreement" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to sign" }));
    expect(await screen.findByText("a phone number")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Sign the agreement" })).toBeDisabled();
  });

  it("asks the owner's page in two parts, with Sleeps, before the reading", async () => {
    vi.stubGlobal("fetch", mockApi({ [`GET ${BASE}`]: page() }));
    render(<AgreementApp brand={BRAND} token={TOKEN} />);
    await screen.findByText("Welcome, Alex!");
    fireEvent.click(screen.getByRole("button", { name: "Fill in your details" }));
    expect(await screen.findByText("Unit information")).toBeInTheDocument();
    expect(screen.getByText("Owner information")).toBeInTheDocument();
    expect(screen.getByLabelText(/^Sleeps/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Alternate phone \(optional\)/)).toBeInTheDocument();
    expect(screen.getByLabelText(/Their mailing address \(optional\)/)).toBeInTheDocument();
    expect(screen.queryByLabelText(/Business phone/)).toBeNull();
  });

  it("tells the first owner who signs next, and still offers onboarding", async () => {
    vi.stubGlobal("fetch", mockApi({ [`GET ${BASE}`]: page({
      state: "signed", owners: [{ position: 1, name: "Alex Sample", signed: true },
                                { position: 2, name: "Pat Sample", signed: false }],
      waiting_for: "Pat Sample" }) }));
    render(<AgreementApp brand={BRAND} token={TOKEN} />);
    expect(await screen.findByText(/Pat Sample signs next/)).toBeInTheDocument();
    expect(screen.getByText(/We'll email you a copy once every owner has signed/))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Complete onboarding now" })).toBeInTheDocument();
  });

  it("a later owner reads and signs, fills nothing in, and gets a thank-you", async () => {
    const co = page({ role: "co_owner", position: 2, first_name: "Pat", details: {},
      owners: [{ position: 1, name: "Alex Sample", signed: true },
               { position: 2, name: "Pat Sample", signed: false }],
      prefill: { name: "Pat Sample", email: "pat@samplehomes.net", phone: "" } });
    vi.stubGlobal("fetch", mockApi({
      [`GET ${BASE}`]: co,
      [`POST ${BASE}/sign`]: { ...co, state: "signed", all_signed: true,
        owners: co.owners.map((o) => ({ ...o, signed: true })) },
    }));
    render(<AgreementApp brand={BRAND} token={TOKEN} />);
    expect(await screen.findByText(/Alex Sample signed the rental management agreement/))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Fill in your details" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Read the agreement" }));
    fireEvent.click(await screen.findByRole("button", { name: "Continue to sign" }));
    fireEvent.change(await screen.findByLabelText("Your name, as your signature"),
                     { target: { value: "Pat Sample" } });
    fireEvent.click(screen.getByLabelText("I agree to sign electronically"));
    fireEvent.click(screen.getByRole("button", { name: "Sign the agreement" }));
    expect(await screen.findByText("Thank you for signing!")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Complete onboarding now" })).toBeNull();
  });

  it("a later owner's link before their turn says who signs first", async () => {
    vi.stubGlobal("fetch", mockApi({ [`GET ${BASE}`]: page({ state: "waiting",
      role: "co_owner", position: 3, first_name: "Lee", waiting_for: "Pat Sample",
      blocks: [] }) }));
    render(<AgreementApp brand={BRAND} token={TOKEN} />);
    expect(await screen.findByText(/Pat Sample signs this agreement first/))
      .toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Read the agreement" })).toBeNull();
  });

  it("an unknown link says so, with nothing else", async () => {
    vi.stubGlobal("fetch", mockApi({ [`GET ${BASE}`]: () => ({ status: 404, body:
      { detail: "This link isn't valid." } }) }));
    render(<AgreementApp brand={BRAND} token={TOKEN} />);
    expect(await screen.findByText("This link isn't valid")).toBeInTheDocument();
  });
});

describe("the welcome's tax line (owner, 2026-11-25)", () => {
  it("says the agreement doesn't ask, and that the onboarding form asks for one tax number",
    async () => {
      vi.stubGlobal("fetch", mockApi({ [`GET ${BASE}`]: page() }));
      render(<AgreementApp brand={BRAND} token={TOKEN} />);
      expect(await screen.findByText("This agreement doesn't ask for your Social Security "
        + "number or bank details. The onboarding form that follows asks for one tax number, "
        + "for your rental permit.")).toBeInTheDocument();
      expect(screen.queryByText(/never asks for your Social Security/)).toBeNull();
    });
});
