/** Form settings and the intake list (owner, 2026-11-24): test mode's latest
 *  change, who may change it, and the links to People and permissions. */
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Me } from "../lib/api";
import type { FormSettings } from "../lib/intake";
import { mockApi, renderRoute } from "../test/render";
import { IntakeScreen } from "./Intake";
import { IntakeSettings } from "./IntakeSettings";

const ME = { role: "FF", full_name: "Bryan Example" } as unknown as Me;
const CO = "11111111-1111-1111-1111-111111111111";

function form(over: Partial<FormSettings> = {}): FormSettings {
  return {
    id: "f1", title: "New owner", brand_name: "Mountain Stays", slug: "mountain", domain: "",
    colors: {}, contact_phone: "", contact_email: "", has_logo: false, has_icon: false,
    base: "", warning: "", test_mode: false, may_change_test_mode: true,
    may_edit_access: true,
    test_mode_change: { to: false, from: true, by: "Michael Example",
                        at: "2026-11-24T16:00:00Z" },
    settings: {
      common_amenities: [], hidden_groups: [], lodging_type_ids: [], code_type_ids: [],
      custom_fields: {}, sleeps: {}, checklist: [],
      message_invite: { subject: "", body: "" }, message_reminder: { subject: "", body: "" },
      new_units_bookable: false, owner_active: true, default_contract_id: null,
      default_management_agreement: "",
    },
    lists: { amenities: [], bed_types: [], code_types: [], custom_fields: [],
             lodging_types: [] },
    lists_status: { fetched_at: null, stale: false, error: "" },
    builtin_fields: {}, checklist_when: [], ...over,
  } as FormSettings;
}

afterEach(() => vi.unstubAllGlobals());

describe("Form settings: test mode", () => {
  it("shows who last changed it and when, and lets the practice owner change it", async () => {
    const api = mockApi({
      [`POST /api/intake/companies/${CO}/test-mode`]: (body: unknown) => ({ body: form({
        test_mode: (body as { on: boolean }).on,
        test_mode_change: { to: true, from: false, by: "Bryan Example",
                            at: "2026-11-24T17:00:00Z" } }) }),
      [`/api/intake/companies/${CO}/form`]: form(),
    });
    vi.stubGlobal("fetch", api);
    renderRoute(<IntakeSettings me={ME} />, { path: "/s/:companyId", route: `/s/${CO}` });
    expect((await screen.findByTestId("test-mode-change")).textContent)
      .toMatch(/Test mode turned off by Michael Example on /);
    fireEvent.click(screen.getByLabelText(/On: check everything, write nothing/));
    await waitFor(() => expect(api.calls.find((c) => c.url.endsWith("/test-mode"))?.body)
      .toEqual({ on: true }));
    expect((await screen.findByTestId("test-mode-change")).textContent)
      .toMatch(/Test mode turned on by Bryan Example on /);
    expect(screen.getByRole("link", { name: "People and permissions" }))
      .toHaveAttribute("href", `/permissions/${CO}`);
  });

  it("shows the state to everyone else, who can't change it", async () => {
    vi.stubGlobal("fetch", mockApi({ [`/api/intake/companies/${CO}/form`]: form({
      test_mode: true, may_change_test_mode: false, may_edit_access: false }) }));
    renderRoute(<IntakeSettings me={ME} />, { path: "/s/:companyId", route: `/s/${CO}` });
    const on = await screen.findByLabelText(/On: check everything, write nothing/);
    expect(on).toBeChecked();
    expect(on).toBeDisabled();
    expect(screen.getByText(/Only the practice owner and the Client owner can turn test mode/))
      .toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "People and permissions" })).toBeNull();
  });
});

describe("the intake list", () => {
  it("links to People and permissions for the people who edit it", async () => {
    vi.stubGlobal("fetch", mockApi({
      [`/api/intake/companies/${CO}/submissions`]: { submissions: [], may_edit_access: true },
      "/api/intake/companies": { companies: [{ id: CO, name: "Mountain Stays" }] },
    }));
    renderRoute(<IntakeScreen me={ME} />, { route: `/?company=${CO}` });
    expect(await screen.findByRole("link", { name: "People and permissions" }))
      .toHaveAttribute("href", `/permissions/${CO}`);
  });
});
