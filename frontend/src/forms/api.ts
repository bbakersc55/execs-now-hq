import type { Answers, FileRow, FormApi, OwnerForm, Secrets, Section } from "./types";

export class FormError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const isForm = body instanceof FormData;
  const response = await fetch(path, {
    method,
    credentials: "omit",
    headers: isForm || body === undefined ? {} : { "Content-Type": "application/json" },
    body: isForm ? (body as FormData) : body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await response.text();
  let data: unknown = null;
  try { data = text ? JSON.parse(text) : null; } catch { data = null; }
  if (!response.ok) {
    const detail = (data as { detail?: string } | null)?.detail;
    throw new FormError(detail || "Something went wrong. Please try again.", response.status);
  }
  return data as T;
}

export interface OwnerPage {
  state: "open" | "submitted";
  number: number;
  form: OwnerForm | null;
  answers: Answers;
  secrets: Secrets;
  files: FileRow[];
  missing: string[];
  first_name: string;
}

/** The owner's side, by the link's token. */
export function ownerApi(token: string): FormApi & {
  load(): Promise<OwnerPage>;
  submit(): Promise<void>;
  another(): Promise<string>;
} {
  const base = `/api/f/${encodeURIComponent(token)}`;
  return {
    load: () => call<OwnerPage>("GET", base),
    async saveSection(section: Section, value: unknown) {
      await call("PATCH", `${base}/answers`, { section, value });
    },
    putSecret: async (kind, slot, value) =>
      (await call<{ secrets: Secrets }>("POST", `${base}/secret`, { kind, slot, value })).secrets,
    clearSecret: async (kind, slot) =>
      (await call<{ secrets: Secrets }>("DELETE", `${base}/secret`, { kind, slot })).secrets,
    async uploadFile(file: File) {
      const body = new FormData();
      body.append("file", file);
      return call<FileRow>("POST", `${base}/files`, body);
    },
    async deleteFile(id: string) {
      await call("DELETE", `${base}/files/${encodeURIComponent(id)}`);
    },
    async submit() {
      await call("POST", `${base}/submit`);
    },
    another: async () => (await call<{ link: string }>("POST", `${base}/another`)).link,
  };
}
