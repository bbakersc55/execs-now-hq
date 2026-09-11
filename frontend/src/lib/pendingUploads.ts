/**
 * AC-2.8(b) — a recording is never lost to a failed upload.
 *
 * When recording stops, the audio is written HERE before the upload is even
 * attempted, and removed only once the server has confirmed it. An offline
 * laptop, a 503 from the bucket, or a closed tab leaves the audio in this
 * browser, and the app retries on the next load.
 *
 * IndexedDB, not memory or localStorage: it survives a reload, and it holds a
 * two-hour Blob that localStorage cannot.
 */
import { api } from "./api";

export interface Pending {
  noteId: string;
  blob: Blob;
  durationSeconds: number;
  savedAt: string;
}

export interface PendingStore {
  put(item: Pending): Promise<void>;
  remove(noteId: string): Promise<void>;
  list(): Promise<Pending[]>;
}

const DB = "execsnowhq";
const STORE = "pending_recordings";

function open(): Promise<IDBDatabase> {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB, 1);
    request.onupgradeneeded = () => request.result.createObjectStore(STORE, { keyPath: "noteId" });
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function run<T>(mode: IDBTransactionMode, body: (s: IDBObjectStore) => IDBRequest<T>): Promise<T> {
  return open().then((db) => new Promise<T>((resolve, reject) => {
    const tx = db.transaction(STORE, mode);
    const request = body(tx.objectStore(STORE));
    tx.oncomplete = () => resolve(request.result);
    tx.onerror = () => reject(tx.error);
  }));
}

export const indexedDbStore: PendingStore = {
  put: (item) => run("readwrite", (s) => s.put(item)).then(() => undefined),
  remove: (noteId) => run("readwrite", (s) => s.delete(noteId)).then(() => undefined),
  list: () => run<Pending[]>("readonly", (s) => s.getAll() as IDBRequest<Pending[]>),
};

let store: PendingStore = indexedDbStore;

/** Tests swap in an in-memory store; jsdom has no IndexedDB. */
export function usePendingStore(replacement: PendingStore) {
  store = replacement;
}

export function memoryStore(): PendingStore & { items: Map<string, Pending> } {
  const items = new Map<string, Pending>();
  return {
    items,
    put: async (item) => { items.set(item.noteId, item); },
    remove: async (noteId) => { items.delete(noteId); },
    list: async () => [...items.values()],
  };
}

export type UploadResult = { ok: true } | { ok: false; kept: true; reason: string };

/** Save first, then upload; forget only on the server's confirmation. */
export async function saveAndUpload(noteId: string, blob: Blob, durationSeconds: number): Promise<UploadResult> {
  await store.put({ noteId, blob, durationSeconds, savedAt: new Date().toISOString() });
  return retry(noteId);
}

export async function retry(noteId: string): Promise<UploadResult> {
  const item = (await store.list()).find((p) => p.noteId === noteId);
  if (!item) return { ok: true };
  const form = new FormData();
  const extension = item.blob.type.includes("ogg") ? "ogg" : "webm";
  form.append("audio", item.blob, `recording.${extension}`);
  form.append("duration_seconds", String(Math.round(item.durationSeconds)));
  try {
    await api.post(`/api/notes/${noteId}/recording/`, form);
  } catch (e) {
    const status = (e as { status?: number }).status;
    if (status === 409) {
      // The server already has this recording (an earlier attempt landed).
      await store.remove(noteId);
      return { ok: true };
    }
    return { ok: false, kept: true, reason: (e as Error).message || "Upload failed." };
  }
  await store.remove(noteId);
  return { ok: true };
}

export function listPending(): Promise<Pending[]> {
  return store.list();
}
