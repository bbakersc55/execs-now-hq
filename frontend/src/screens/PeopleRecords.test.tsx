import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChecklistFull, PeopleScopePage, PersonPage } from "../lib/api";
import { mockApi, renderRoute } from "../test/render";
import { PeopleScope, PersonScreen } from "./People";

/** 2026-11-17: the employee records, their pages, checklists and setup. */

const ACME = "11111111-2222-4333-8444-555555555555";
const sent = (fetchMock: ReturnType<typeof mockApi>, suffix: string) =>
  fetchMock.calls.filter((c) => c.method !== "GET" && c.url.endsWith(suffix)).map((c) => c.body);

beforeEach(() => { vi.unstubAllGlobals(); });

const person = (id: string, name: string, more = {}) => ({
  id, name, first_name: name.split(" ")[0], last_name: name.split(" ")[1] ?? "",
  title: "Machinist", department: "Production", team: "Floor",
  work_email: `${id}@acme.example`, work_phone: "", manager: null, own: false,
  placeholder: false, status: "active" as const, status_label: "Active",
  employment_type: "full_time" as const, employment_type_label: "Employee, full-time",
  work_state: "UT", start_date: "2021-12-01", ended_on: null, has_sign_in: true, ...more });

const directory = (more: Partial<PeopleScopePage> = {}): PeopleScopePage => ({
  guidance: "HR guidance, not legal advice", key: ACME, name: "Acme Fasteners",
  level: "director", level_label: "HR Director", manages: true, may_add: true,
  may_export: true, may_export_sensitive: true, may_run: true, may_hire: true, members: [],
  records: [person("p1", "Marvin Martian", { title: "Shop lead" }),
            person("p2", "Daffy Duck", { department: "Shipping", status: "on_leave",
                                         status_label: "On leave" }),
            person("p3", "Elmer Fudd", { employment_type: "contractor",
                                         employment_type_label: "Contractor" })],
  headcount: [{ status: "active", label: "Active", count: 2 },
              { status: "on_leave", label: "On leave", count: 1 }],
  upcoming: { anniversaries: [{ id: "p1", name: "Marvin Martian", on: "2026-12-01", years: 5 }],
              birthdays: [{ id: "p2", name: "Daffy Duck", day: "December 5" }] },
  chart: { type: "org_chart", svg: "<svg xmlns='http://www.w3.org/2000/svg'></svg>", width: 400,
           height: 200, label: "Org chart: 3 people, drawn from their managers (1 at the top)." },
  client_users: { sign_ins: 5, records_without_sign_in: 1, total: 6, blocks: 1, block_size: 25,
                  cents: 1000 },
  fields: [], my_items: [], to_sign: [], held_in_payroll: "Held in payroll, not here.",
  ...more });

function showScope(routes: Record<string, unknown>) {
  const fetchMock = mockApi(routes);
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<PeopleScope />, { path: "/people/:scope", route: `/people/${ACME}` });
  return fetchMock;
}

describe("the directory", () => {
  it("searches and filters, with headcount, the month ahead and client users", async () => {
    showScope({ [`GET /api/people/${ACME}/`]: directory() });
    const table = await screen.findByRole("table", { name: "Directory" });
    expect(within(table).getAllByRole("row")).toHaveLength(4);
    await userEvent.type(screen.getByLabelText("Search people"), "daffy");
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    await userEvent.clear(screen.getByLabelText("Search people"));
    await userEvent.selectOptions(screen.getByLabelText("Employment type"), "contractor");
    expect(within(table).getByText("Elmer Fudd")).toBeInTheDocument();
    expect(within(table).queryByText("Marvin Martian")).toBeNull();
    expect(screen.getByRole("list", { name: "Anniversaries and birthdays" }))
      .toHaveTextContent("Daffy Duck: birthday, December 5");
    expect(screen.getByText(/Client users here: 6/)).toHaveTextContent("1 block of 25");
    expect(screen.getByRole("link", { name: "Export with sensitive fields" }))
      .toHaveAttribute("href", `/api/people/${ACME}/export/?sensitive=1`);
    await userEvent.click(screen.getByRole("tab", { name: "Org chart" }));
    expect(screen.getByRole("img", { name: /Org chart: 3 people/ })).toBeInTheDocument();
  });

  it("adds a person to hire with an offer, and says what is held in payroll", async () => {
    const fetchMock = showScope({
      [`GET /api/people/${ACME}/`]: directory(),
      [`POST /api/people/${ACME}/records/`]: () => ({ status: 201, body: {} }),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Add a person" }));
    const form = screen.getByRole("form", { name: "Add a person" });
    expect(form).toHaveTextContent("Held in payroll, not here.");
    await userEvent.type(within(form).getByLabelText("First name"), "Wile");
    await userEvent.type(within(form).getByLabelText("Title"), "Engineer");
    await userEvent.type(within(form).getByLabelText("Pay rate"), "85,000");
    await userEvent.selectOptions(within(form).getByLabelText("Pay unit"), "year");
    await userEvent.click(within(form).getByLabelText(/Hiring: start as "offer out"/));
    await userEvent.click(within(form).getByRole("button", { name: "Add" }));
    expect(sent(fetchMock, "/records/")).toEqual([{
      first_name: "Wile", title: "Engineer", employment_type: "full_time", offer: true,
      sensitive: { pay_rate: "85,000", pay_unit: "year" } }]);
  });

  it("shows an employee their documents to sign and items, and finishes one", async () => {
    const own = directory({
      level: "self", level_label: "Your own record", manages: false, may_add: false,
      may_export: false, may_export_sensitive: false, may_run: false, may_hire: false,
      records: [person("p2", "Daffy Duck", { own: true })], headcount: null, upcoming: null,
      chart: null, client_users: null,
      to_sign: [{ id: "d1", title: "Employee handbook acknowledgment",
                  kind_label: "Handbook acknowledgment", state_label: "Sent",
                  sent_at: "2026-11-17T15:00:00Z" }],
      my_items: [{ id: "i1", section: "people", section_label: "People",
                   title: "Complete payroll setup with the payroll provider", owner: "Daffy",
                   mine: true, due_date: "2026-12-01", done: false, waived: false,
                   waive_note: "", revokes: null, task: "t1", person: "Daffy Duck",
                   person_id: "p2", kind: "onboarding", kind_label: "Onboarding" }] });
    const fetchMock = showScope({
      [`GET /api/people/${ACME}/`]: own,
      [`POST /api/people/${ACME}/items/i1/done/`]: () => ({ body: {} }),
    });
    expect(await screen.findByRole("list", { name: "Documents to sign" }))
      .toHaveTextContent("Employee handbook acknowledgment");
    await userEvent.click(screen.getByRole("button",
      { name: "Done: Complete payroll setup with the payroll provider" }));
    expect(sent(fetchMock, "/items/i1/done/")).toHaveLength(1);
    expect(screen.queryByRole("tab", { name: "Checklists and fields" })).toBeNull();
  });

  it("shows a manager their reports' checklist progress", async () => {
    showScope({ [`GET /api/people/${ACME}/`]: directory({
      level: "reports", level_label: "Manager (direct reports)", manages: false,
      may_add: false, may_export: false, may_export_sensitive: false, may_run: false,
      may_hire: false, headcount: null, upcoming: null, chart: null, client_users: null,
      records: [person("p3", "Elmer Fudd", { status: undefined, status_label: undefined,
        progress: [{ id: "c1", kind: "offboarding", kind_label: "Offboarding", done: 3,
                     waived: 1, total: 9, closed: false, anchor_date: "2026-12-15" }] })] }) });
    expect(await screen.findByText(/Offboarding 4 of 9/)).toBeInTheDocument();
  });
});

const checklist = (more: Partial<ChecklistFull> = {}): ChecklistFull => ({
  id: "c1", kind: "offboarding", kind_label: "Offboarding", done: 1, waived: 0, total: 2,
  closed: false, anchor_date: "2026-12-15", reason: "resignation", reason_label: "Resignation",
  note: "", started_at: "2026-11-17T15:00:00Z", closed_at: null,
  owners: { hr: "Bryan", it: "Bryan", manager: "Marvin" }, custom: [],
  items: [
    { id: "i1", section: "people", section_label: "People", title: "Hold the exit interview",
      owner: "Bryan", mine: true, due_date: "2026-12-14", done: true, waived: false,
      waive_note: "", revokes: null, task: "t1" },
    { id: "i2", section: "it", section_label: "IT", title: "Revoke system: Slack",
      owner: "Bryan", mine: true, due_date: "2026-12-15", done: false, waived: false,
      waive_note: "", revokes: "a1", task: "t2" }],
  can_close: false,
  no_payroll: "This doesn't end anyone in payroll: a person does that in the payroll provider.",
  ...more });

const page = (more: Partial<PersonPage> = {}): PersonPage => ({
  ...person("p2", "Daffy Duck"),
  employment: { status: "offboarding", status_label: "Offboarding",
                employment_type: "full_time", employment_type_label: "Employee, full-time",
                work_state: "UT", start_date: "2021-12-01", ended_on: null, has_sign_in: true },
  custom: [{ id: "f1", label: "Shirt size", value: "Large" }],
  held_in_payroll: "Held in payroll, not here.",
  sensitive: { pay_rate: "31.75", pay_unit: "hour", pay_effective_on: "2026-01-01",
               home_address: "12 Canyon Road", date_of_birth: "1990-12-05",
               personal_phone: "801-555-0199", personal_email: "daffy@home.example",
               emergency_contact: "A sibling" },
  masked: false,
  documents: [{ id: "d1", kind: "offer_letter", kind_label: "Offer letter",
                title: "Offer of employment: Machinist", added_at: "2021-11-01T00:00:00Z",
                signature: { state: "complete", state_label: "Complete", document_id: "e1" },
                has_file: true }],
  checklists: [checklist()],
  access: [{ id: "a1", kind: "system", kind_label: "System", name: "Slack", detail: "",
             given_on: "2025-01-06", given_by: "Acme IT", revoked_at: null, revoked_by: "" }],
  to_sign: [],
  may: { edit: true, run: true, offer: false, handbook: true, upload: true },
  owners: [{ id: "u1", name: "Bryan", side: "practice" }],
  checklist_fields: { onboarding: [], offboarding: [] },
  reasons: [{ value: "resignation", label: "Resignation" }],
  ...more });

function showPerson(routes: Record<string, unknown>) {
  const fetchMock = mockApi(routes);
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<PersonScreen />, { path: "/people/:scope/:person",
                                  route: `/people/${ACME}/p2` });
  return fetchMock;
}

describe("a person's page", () => {
  it("shows the record by section, the access list and the offboarding", async () => {
    showPerson({ [`GET /api/people/${ACME}/records/p2/`]: page(),
                 [`GET /api/people/${ACME}/`]: directory() });
    expect(await screen.findByLabelText("Pay")).toHaveTextContent("31.75 an hour");
    expect(screen.getByLabelText("Personal details")).toHaveTextContent("12 Canyon Road");
    expect(screen.getByLabelText("Employment fields")).toHaveTextContent("Shirt size");
    expect(screen.getByRole("table", { name: "Access list" })).toHaveTextContent("Acme IT");
    const off = screen.getByRole("region", { name: "Offboarding: IT" });
    expect(off).toHaveTextContent("Revoke system: Slack");
    expect(screen.getByText(/This doesn't end anyone in payroll/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Close the offboarding" })).toBeDisabled();
    expect(screen.getByRole("link", { name: "Download" })).toHaveAttribute(
      "href", `/api/people/${ACME}/documents/d1/`);
    expect(screen.getByText(/Don't upload Social Security cards/)).toBeInTheDocument();
  });

  it("waives an item only with a note, and finishes one", async () => {
    const fetchMock = showPerson({
      [`GET /api/people/${ACME}/records/p2/`]: page(),
      [`GET /api/people/${ACME}/`]: directory(),
      [`POST /api/people/${ACME}/items/i2/waive/`]: () => ({ body: {} }),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Waive: Revoke system: Slack" }));
    const waive = screen.getByRole("button", { name: "Waive it" });
    expect(waive).toBeDisabled();
    await userEvent.type(screen.getByLabelText("Why it is waived"), "Account deleted by vendor");
    await userEvent.click(waive);
    expect(sent(fetchMock, "/items/i2/waive/")).toEqual([{ note: "Account deleted by vendor" }]);
  });

  it("masks for a Generalist and offers no upload or edit", async () => {
    showPerson({ [`GET /api/people/${ACME}/records/p2/`]: page({
      masked: true, documents: "1 document",
      sensitive: { pay_rate: "•••••", pay_unit: "•••••", pay_effective_on: "•••••",
                   home_address: "•••••", date_of_birth: "•••••", personal_phone: "•••••",
                   personal_email: "•••••", emergency_contact: "•••••" },
      may: { edit: false, run: true, offer: false, handbook: true, upload: false } }) });
    expect(await screen.findByText("1 document")).toBeInTheDocument();
    expect(screen.getByLabelText("Pay")).not.toHaveTextContent("31.75");
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    expect(screen.queryByRole("form", { name: "Add a document" })).toBeNull();
  });

  it("starts an offboarding with a last day and a reason", async () => {
    const fetchMock = showPerson({
      [`GET /api/people/${ACME}/records/p2/`]: page({ checklists: [],
        employment: { ...page().employment!, status: "active", status_label: "Active" } }),
      [`GET /api/people/${ACME}/`]: directory(),
      [`POST /api/people/${ACME}/records/p2/checklists/`]: () => ({ status: 201, body: {} }),
    });
    const form = await screen.findByRole("form", { name: "Start offboarding" });
    const start = within(form).getByRole("button", { name: "Start offboarding" });
    expect(start).toBeDisabled();
    await userEvent.type(within(form).getByLabelText("Last day"), "2026-12-15");
    await userEvent.selectOptions(within(form).getByLabelText("Reason"), "resignation");
    await userEvent.click(start);
    expect(sent(fetchMock, "/records/p2/checklists/")).toEqual([{
      kind: "offboarding", anchor_date: "2026-12-15", it_owner: null, reason: "resignation",
      custom: {} }]);
  });
});

describe("the company's checklists and fields", () => {
  it("adds an item and reorders", async () => {
    const setup = {
      items: { onboarding: [
        { id: "t1", kind: "onboarding", section: "people", section_label: "People",
          title: "Send the welcome email", owner_role: "hr", owner_role_label: "Whoever starts it",
          due_days: -5, standard: true },
        { id: "t2", kind: "onboarding", section: "it", section_label: "IT",
          title: "Order the laptop", owner_role: "it", owner_role_label: "The IT owner",
          due_days: -5, standard: true }], offboarding: [] },
      fields: { record: [], onboarding: [], offboarding: [] },
      held_in_payroll: "Held in payroll, not here." };
    const fetchMock = showScope({
      [`POST /api/people/${ACME}/setup/items/reorder/`]: () => ({ body: setup }),
      [`POST /api/people/${ACME}/setup/items/`]: () => ({ body: setup }),
      [`GET /api/people/${ACME}/setup/`]: setup,
      [`GET /api/people/${ACME}/`]: directory(),
    });
    await userEvent.click(await screen.findByRole("tab", { name: "Checklists and fields" }));
    const add = await screen.findByRole("form", { name: "Add to the onboarding checklist" });
    await userEvent.selectOptions(within(add).getByLabelText("Section"), "it");
    await userEvent.type(within(add).getByLabelText("Item"), "Add them to the ERP");
    await userEvent.click(within(add).getByRole("button", { name: "Add" }));
    expect(sent(fetchMock, "/setup/items/")).toEqual([{ kind: "onboarding", section: "it",
      title: "Add them to the ERP", owner_role: "it", due_days: 0 }]);
    await userEvent.click(screen.getByRole("button", { name: "Move down: Send the welcome email" }));
    expect(sent(fetchMock, "/setup/items/reorder/")).toEqual([{ kind: "onboarding",
      ids: ["t2", "t1"] }]);
  });
});
