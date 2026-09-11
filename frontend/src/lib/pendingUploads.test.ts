import { beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../test/render";
import { memoryStore, retry, saveAndUpload, usePendingStore } from "./pendingUploads";

/**
 * AC-2.8(b), as re-worded 2026-09-11: when the upload fails, the recording
 * stays in the browser and is retried until the server confirms it.
 */
describe("pending recordings", () => {
  let store: ReturnType<typeof memoryStore>;
  beforeEach(() => {
    vi.unstubAllGlobals();
    store = memoryStore();
    usePendingStore(store);
  });
  const audio = () => new Blob(["opus audio"], { type: "audio/webm;codecs=opus" });

  it("keeps the audio when the server is unreachable, and forgets it only on confirmation", async () => {
    let up = false;
    vi.stubGlobal("fetch", mockApi({
      "POST /api/notes/n1/recording/": () => up
        ? { status: 201, body: {} }
        : { status: 503, body: { detail: "Storage is unreachable right now." } },
    }));

    const first = await saveAndUpload("n1", audio(), 95);
    expect(first).toEqual({ ok: false, kept: true, reason: "Storage is unreachable right now." });
    expect(store.items.get("n1")?.durationSeconds).toBe(95);

    up = true;
    expect(await retry("n1")).toEqual({ ok: true });
    expect(store.items.size).toBe(0);
  });

  it("keeps the audio when the network itself fails", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    const result = await saveAndUpload("n2", audio(), 10);
    expect(result.ok).toBe(false);
    expect(store.items.has("n2")).toBe(true);
  });

  it("writes to the browser BEFORE attempting the upload", async () => {
    let heldDuringUpload = false;
    vi.stubGlobal("fetch", mockApi({
      "POST /api/notes/n3/recording/": () => { heldDuringUpload = store.items.has("n3"); return { status: 201, body: {} }; },
    }));
    await saveAndUpload("n3", audio(), 10);
    expect(heldDuringUpload).toBe(true);
  });

  it("treats 'already has a recording' as delivered", async () => {
    vi.stubGlobal("fetch", mockApi({
      "POST /api/notes/n4/recording/": () => ({ status: 409, body: { detail: "This note already has a recording." } }),
    }));
    expect(await saveAndUpload("n4", audio(), 10)).toEqual({ ok: true });
    expect(store.items.size).toBe(0);
  });

  it("never discards audio the server refused for another reason", async () => {
    vi.stubGlobal("fetch", mockApi({
      "POST /api/notes/n5/recording/": () => ({ status: 400, body: { detail: "Recordings are capped at 120 minutes." } }),
    }));
    const result = await saveAndUpload("n5", audio(), 10);
    expect(result.ok).toBe(false);
    expect(store.items.has("n5")).toBe(true);
  });
});
