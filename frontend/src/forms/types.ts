/** The owner's intake form: what the server sends, and the answers' shape.
 *  This folder is its own bundle (vite.forms.config.ts): it imports nothing
 *  from the rest of the app, so nothing of the app can reach an owner. */

export type Option = { value: string; label: string };

export interface Brand {
  brand_name: string;
  title: string;
  slug: string;
  colors: Record<string, string>;
  contact_phone: string;
  contact_email: string;
  logo: string;
  icon: string;
}

export interface OwnerForm {
  sections: { key: string; title: string }[];
  options: Record<string, Option[]>;
  builtin: Record<string, boolean>;
  bed_types: { id: number; label: string; sleeps: number; other_places: boolean }[];
  bathroom_fixtures: { id: number; name: string; kind: string }[];
  common_amenities: { key: string; label: string }[];
  amenity_groups: { name: string; amenities: { id: number; name: string }[] }[];
  lodging_types: { id: number; name: string }[];
  code_types: { id: number; name: string }[];
  trash_days: Option[];
  custom_fields: {
    reference: string; label: string; help: string; type: string; section: string;
    options: Option[];
  }[];
}

export interface Bed { type: number; count: number }
export interface Range { start: string; end: string }
export interface ExtraOwner {
  first_name: string; last_name: string; email: string; mobile: string; portal: boolean;
}

export interface About {
  first_name?: string; last_name?: string; account_name?: string;
  street?: string; street2?: string; city?: string; state?: string; postal?: string;
  country?: string; mobile?: string; email?: string; contact_pref?: string; heard?: string;
  heard_detail?: string; has_extra_owners?: string; extra_owners?: ExtraOwner[];
}
export interface Property {
  street?: string; street2?: string; city?: string; state?: string; postal?: string;
  lodging_type_id?: number | null; ready?: string; ready_date?: string;
  has_bookings?: string; bookings?: Range[];
}
export interface Bedroom { beds: Bed[]; own_bath: boolean }
export interface Place { where: string; label: string; beds: Bed[] }
export interface Home {
  heating?: string[]; cooling?: string[]; hvac_note?: string;
  parking?: string[]; parking_pass?: string; parking_note?: string;
  wifi?: string; wifi_provider?: string; wifi_network?: string; wifi_router?: string;
  tv?: string[]; tv_count?: number; tv_provider?: string; tv_note?: string;
  trash_by?: string; trash_provider?: string; trash_days?: string[]; trash_note?: string;
  hoa?: string; hoa_company?: string; hoa_contact?: string; hoa_phone?: string;
  hoa_email?: string; hoa_note?: string;
  heat_tape?: string; heat_tape_by?: string;
  snow_by?: string; snow_provider?: string; snow_note?: string;
  landscaping_by?: string; landscaping_note?: string;
  softener?: string; softener_note?: string;
  permit?: string; permit_number?: string;
}
export interface Access {
  door?: string; owner_closet?: string; alarm?: string; extra_codes?: { type: number }[];
}

export interface Answers {
  about?: About;
  tax?: { kind?: string };
  property?: Property;
  bedrooms?: Bedroom[];
  other_sleeping?: { has?: string; places?: Place[] };
  bathrooms?: { fixtures: Record<string, number> }[];
  amenities?: { common?: string[]; more?: number[]; gondola?: string };
  home?: Home;
  access?: Access;
  stays?: { has?: string; ranges?: Range[] };
  custom?: Record<string, string | string[]>;
}

export type Section = keyof Answers;

export interface Secrets {
  tax_id: { last4: string } | null;
  wifi_password: boolean;
  codes: Record<string, boolean>;
}

export interface FileRow { id: string; name: string; size: number }

/** How a section saves: the owner's link, or the review screen in the app. */
export interface FormApi {
  saveSection(section: Section, value: unknown): Promise<void>;
  putSecret(kind: string, slot: string, value: string): Promise<Secrets>;
  clearSecret(kind: string, slot: string): Promise<Secrets>;
  uploadFile(file: File): Promise<FileRow>;
  deleteFile(id: string): Promise<void>;
  fileUrl?(id: string): string;
}

export interface Ctx {
  form: OwnerForm;
  answers: Answers;
  update: <K extends Section>(section: K, value: Answers[K]) => void;
  secrets: Secrets;
  setSecrets: (s: Secrets) => void;
  files: FileRow[];
  setFiles: (f: FileRow[]) => void;
  api: FormApi;
  brand: string;
  /** "staff" on the review screen: the same questions, a reviewer's wording. */
  mode: "owner" | "staff";
  /** The review screen only: each sensitive value the send needs, by name
   *  ("code:door"), and whether it is held, done in Track, marked as none or
   *  missing; and the way to mark one as having none, or undo that. */
  needs?: Record<string, SecretState>;
  markNone?: (name: string, none: boolean) => Promise<void>;
}

export type SecretState = "held" | "sent" | "none" | "missing";
