/** Intake forms, the staff side (apps/intake/views.py). */
import { api } from "./api";
import type { Answers, FileRow, FormApi, OwnerForm, Secrets, Section } from "../forms/types";

export interface IntakeRow {
  id: string; number: number; status: string; status_label: string; owner: string;
  property: string; link_open: boolean; expires_at: string; created_at: string;
  submitted_at: string | null; sent_at: string | null;
}

export interface Step { key: string; label: string; state: string; detail: string }
export interface Run {
  id: string; state: string; steps: Step[]; error: string; created_at: string;
  finished_at: string | null;
}
export interface OwnerDateRow {
  id: string; start: string; end: string; state: string; state_label: string; message: string;
}
export interface Room {
  key: string; name: string; roomType: string; worked_out?: string; sleeps: number;
  summary: string;
}
export interface Staff {
  node_id: number | null; contract_id: number | null; management_agreement: string;
  start_date: string; contract_effective_date: string; unit_type_id: number | null;
  unit_name: string; short_name: string; bath_types: Record<string, string>;
  sleeps_total: number | null; shares: Record<string, number>; untick: number[];
  keywords: string[] | null; custom: Record<string, string | string[]>;
  owner_mode: "new" | "existing"; existing_owner_id: number | null;
  reuse_contacts: Record<string, number>;
}
export interface Named { id: number; name: string; [k: string]: unknown }

export interface Review extends IntakeRow {
  locked: boolean; owner_may_edit: boolean;
  invite: { first_name: string; last_name: string; email: string };
  link: string;
  form: { title: string; brand_name: string; domain: string; company: string;
          company_id: string };
  answers: Answers; secrets: Secrets;
  owner_form: OwnerForm;
  lists: { nodes: (Named & { typeName?: string })[]; contracts: Named[];
           unit_types: Named[]; lodging_types: Named[]; code_types: Named[] };
  staff_fields: { reference: string; name: string; type: string;
                  values: { value: string; label: string }[] }[];
  lists_status: { fetched_at: string | null };
  staff: Staff;
  derived: {
    rooms: Room[]; counts: Record<string, number>; sleeps_worked_out: number;
    sleeps_total: number;
    derived_amenities: { id: number; name: string; why: string; provided_by_area: boolean;
                         ticked: boolean }[];
    amenities: { id: number; name: string; why: string }[];
    custom: Record<string, unknown>; keyword_presets: string[];
    codes: { slot: string; type_id: number; label: string }[];
    unit_type_suggested: number | null;
  };
  plan: { mode: string; summary: string[]; problems: string[]; warnings: string[];
          steps: { key: string; label: string }[] };
  check: {
    owners?: { id: number; name: string; isActive?: boolean }[];
    contacts?: Record<string, { id: number; name: string }[]>;
    units?: { id: number; name: string; isActive?: boolean }[];
    differences?: { field: string; intake: string; track: string }[];
    error?: string;
  };
  checked_at: string | null;
  files: (FileRow & { content_type: string })[];
  events: { kind: string; label: string; detail: string; who: string; at: string }[];
  run: Run | null;
  owner_dates: OwnerDateRow[];
  may_send: boolean;
  is_practice: boolean;
  people: { first: string; last: string; email: string; mobile: string; portal: boolean }[];
}

export interface FormSettings {
  id: string; title: string; brand_name: string; slug: string; domain: string;
  colors: Record<string, string>; contact_phone: string; contact_email: string;
  has_logo: boolean; has_icon: boolean; base: string; warning: string;
  settings: {
    common_amenities: { key: string; label: string; amenity_ids: number[] }[];
    hidden_groups: string[]; lodging_type_ids: number[]; code_type_ids: number[];
    custom_fields: Record<string, { state: string; label: string; help: string;
                                    section: string }>;
    sleeps: Record<string, { sleeps: number; label: string; confirmed: boolean;
                             other_places: boolean }>;
    checklist: { key?: string; title: string; offset_days: number; when: string }[];
    message_invite: { subject: string; body: string };
    message_reminder: { subject: string; body: string };
    new_units_bookable: boolean; owner_active: boolean;
    default_contract_id: number | null; default_management_agreement: string;
  };
  lists: Record<string, (Named & Record<string, unknown>)[]>;
  lists_status: { fetched_at: string | null; stale: boolean; error: string };
  builtin_fields: Record<string, string>;
  checklist_when: string[];
}

export const intake = {
  companies: () => api.get<{ companies: { id: string; name: string }[] }>("/api/intake/companies"),
  submissions: (company: string) =>
    api.get<{ submissions: IntakeRow[] }>(`/api/intake/companies/${company}/submissions`),
  start: (company: string, body: { first_name: string; last_name: string; email: string }) =>
    api.post<{ id: string; number: number }>(`/api/intake/companies/${company}/submissions`, body),
  review: (id: string) => api.get<Review>(`/api/intake/submissions/${id}`),
  staff: (id: string, changes: Partial<Staff>) =>
    api.patch<Review>(`/api/intake/submissions/${id}/staff`, { changes }),
  check: (id: string) => api.post<Review>(`/api/intake/submissions/${id}/check`),
  link: (id: string, action: "link" | "message" | "email", reminder: boolean) =>
    api.post<{ link: string; subject: string; body: string; mailto: string; to: string;
               expired: boolean }>(`/api/intake/submissions/${id}/link`, { action, reminder }),
  reopen: (id: string) => api.post<Review>(`/api/intake/submissions/${id}/reopen`),
  discard: (id: string) => api.post<Review>(`/api/intake/submissions/${id}/discard`),
  send: (id: string) => api.post<{ run: Run }>(`/api/intake/submissions/${id}/send`),
  run: (id: string) =>
    api.get<{ run: Run | null; status: string; locked: boolean }>(
      `/api/intake/submissions/${id}/run`),
  reveal: (id: string, name: string) =>
    api.post<{ value: string }>(`/api/intake/submissions/${id}/reveal`, { name }),
  placeDates: (id: string) =>
    api.post<{ result: { text: string }; owner_dates: OwnerDateRow[] }>(
      `/api/intake/submissions/${id}/dates/place`),
  cancelDate: (id: string, dateId: string) =>
    api.post<{ owner_dates: OwnerDateRow[] }>(
      `/api/intake/submissions/${id}/dates/${dateId}/cancel`),
  form: (company: string) => api.get<FormSettings>(`/api/intake/companies/${company}/form`),
  saveForm: (company: string, body: Record<string, unknown>) =>
    api.put<FormSettings>(`/api/intake/companies/${company}/form`, body),
  refresh: (company: string) =>
    api.post<FormSettings>(`/api/intake/companies/${company}/refresh`),
  uploadImage: (company: string, which: "logo" | "icon", file: File) => {
    const body = new FormData();
    body.append("which", which);
    body.append("file", file);
    return api.post<{ ok: boolean }>(`/api/intake/companies/${company}/form/image`, body);
  },
};

/** The review screen's sections save here: the same sections as the owner's. */
export function staffFormApi(id: string): FormApi {
  const base = `/api/intake/submissions/${id}`;
  return {
    async saveSection(section: Section, value: unknown) {
      await api.patch(`${base}/answers`, { section, value });
    },
    putSecret: async (kind, slot, value) =>
      (await api.post<{ secrets: Secrets }>(`${base}/secret`, { kind, slot, value })).secrets,
    clearSecret: async (kind, slot) =>
      (await api.delWith<{ secrets: Secrets }>(`${base}/secret`, { kind, slot })).secrets,
    async uploadFile(file: File) {
      const body = new FormData();
      body.append("file", file);
      return api.post<FileRow>(`${base}/files`, body);
    },
    async deleteFile(fileId: string) {
      await api.del(`${base}/files/${fileId}`);
    },
    fileUrl: (fileId: string) => `${base}/files/${fileId}`,
  };
}

export const STATUS_KIND: Record<string, string> = {
  draft: "", in_progress: "info", submitted: "warn", sending: "info", failed: "danger",
  sent: "ok", discarded: "",
};
