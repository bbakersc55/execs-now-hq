import { Company, Contact, ContactType, Me, Pipeline } from "../lib/api";

/**
 * Shapes copied from a real `/api/contacts/` response against the owner's
 * imported book, so a fixture cannot quietly drift from what the API sends.
 */
export const COMPANY_ID = "562aed44-e241-4ab0-adf0-b6161c63c47c";

export function aCompany(overrides: Partial<Company> = {}): Company {
  return {
    id: COMPANY_ID,
    name: "Adapt CFO",
    industry: "Financial services",
    is_client_company: true,
    seat_count: 3,
    seats_in_use: 2,
    seats_available: 1,
    primary_contact: null,
    ...overrides,
  };
}

export function aContact(overrides: Partial<Contact> = {}): Contact {
  return {
    id: "c003672d-6af5-4b7b-b046-4ae9d66d89ef",
    first_name: "Hassam",
    last_name: "Khan",
    title: "Operations Lead",
    company: COMPANY_ID,
    owner: "e00be515-7000-4f5d-96cb-37c3ca330a7f",
    source: "Webinar",
    background: "",
    tags: ["webinar: sign up"],
    emails: [{ id: "e1", address: "hassam@example.invalid", is_primary: true }],
    phones: [{ id: "p1", number: "18578329806", is_primary: true }],
    type_codes: ["prospect"],
    pipeline_positions: [
      {
        pipeline: "639c874c-218a-463a-acdd-a3c43226ce8b",
        pipeline_name: "Sales",
        pipeline_kind: "sales",
        stage: "9792cba6-f256-43b3-ae75-659700bf8ef3",
        stage_code: "prospecting",
        stage_label: "Prospecting",
        semantic: "working",
        entered_at: "2026-09-11T00:16:58.077737Z",
      },
    ],
    referral_fee_terms: "",
    referral_cadence: "",
    referral_touch_mode: "ai",
    referral_next_touch_at: null,
    referral_onboarded_at: null,
    created_at: "2026-09-11T00:16:58.068612Z",
    updated_at: "2026-09-11T00:16:58.068622Z",
    ...overrides,
  };
}


export function aMe(overrides: Partial<Me> = {}): Me {
  return {
    authenticated: true,
    email: "bryan.baker@getexecutivesnow.com",
    full_name: "Bryan Baker",
    role: "FF",
    tenant: "t1",
    client_company: null,
    ...overrides,
  };
}

export const CONTACT_TYPES: ContactType[] = [
  { id: "t-prospect", code: "prospect", label: "Prospect", position: 0 },
  { id: "t-client", code: "client", label: "Client", position: 1 },
  { id: "t-referral", code: "referral_partner", label: "Referral partner", position: 2 },
];

export const PIPELINES: Pipeline[] = [
  {
    id: "p-sales", name: "Sales", kind: "sales", position: 0, contact_count: 0,
    stages: [
      { id: "s-entry", pipeline: "p-sales", code: "initial_contact_made",
        label: "Initial Contact Made", semantic: "entry", position: 0, is_terminal: false },
      { id: "s-qual", pipeline: "p-sales", code: "qualified", label: "Qualified",
        semantic: "qualified", position: 3, is_terminal: false },
    ],
  },
  {
    id: "p-ref", name: "Referral partners", kind: "referral", position: 1, contact_count: 0,
    stages: [
      { id: "s-new", pipeline: "p-ref", code: "new_partner", label: "New Partner",
        semantic: "entry", position: 0, is_terminal: false },
    ],
  },
];
