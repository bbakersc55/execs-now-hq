import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { mockApi } from "../test/render";
import { MAX_SECONDS, Recorder, WARN_AT_SECONDS } from "./Recorder";

class FakeMediaRecorder {
  static isTypeSupported = () => true;
  static last: FakeMediaRecorder | null = null;
  state: "inactive" | "recording" = "inactive";
  mimeType: string;
  ondataavailable: ((e: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  constructor(_stream: unknown, opts: { mimeType: string }) {
    this.mimeType = opts.mimeType;
    FakeMediaRecorder.last = this;
  }
  start() { this.state = "recording"; }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["opus"], { type: this.mimeType }) });
    this.onstop?.();
  }
}

const getUserMedia = vi.fn(async () => ({ getTracks: () => [{ stop: vi.fn() }] }));

async function flush() {
  await act(async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); });
}

function setup(dismissed: boolean) {
  const fetchMock = mockApi({
    "GET /api/notes/consent-reminder/": { dismissed },
    "POST /api/notes/consent-reminder/": { dismissed: true },
  });
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("MediaRecorder", FakeMediaRecorder);
  Object.defineProperty(navigator, "mediaDevices", { value: { getUserMedia }, configurable: true });
  const onComplete = vi.fn();
  render(<Recorder onComplete={onComplete} />);
  return { fetchMock, onComplete };
}

describe("Recorder", () => {
  beforeEach(() => { vi.unstubAllGlobals(); getUserMedia.mockClear(); });
  afterEach(() => vi.useRealTimers());

  it("AC-2.6 — shows the consent reminder before recording, and confirming dismisses it for the session", async () => {
    const { fetchMock } = setup(false);
    fireEvent.click(screen.getByRole("button", { name: /Record/ }));
    const reminder = await screen.findByRole("alertdialog", { name: "Recording consent" });
    expect(reminder).toHaveTextContent("confirm they agree");
    expect(getUserMedia).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Everyone has agreed/ }));
    await screen.findByText("● REC");
    expect(fetchMock.calls.some((c) => c.method === "POST" && c.url.includes("consent-reminder"))).toBe(true);
    expect(getUserMedia).toHaveBeenCalledOnce();
  });

  it("AC-2.6 — once dismissed this session, the next recording starts without it", async () => {
    setup(true);
    fireEvent.click(screen.getByRole("button", { name: /Record/ }));
    await screen.findByText("● REC");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
  });

  it("AC-2.5a — warns at 110 minutes and stops cleanly at 120, keeping what was captured", async () => {
    const { onComplete } = setup(true);
    vi.useFakeTimers({ toFake: ["setInterval", "clearInterval", "Date"] });
    fireEvent.click(screen.getByRole("button", { name: /Record/ }));
    await flush();
    expect(screen.getByText("● REC")).toBeInTheDocument();

    act(() => { vi.advanceTimersByTime((WARN_AT_SECONDS - 5) * 1000); });
    expect(screen.queryByText(/stops automatically at/)).not.toBeInTheDocument();

    act(() => { vi.advanceTimersByTime(10 * 1000); });
    expect(screen.getByText(/stops automatically at\s+120 minutes/)).toBeInTheDocument();
    expect(onComplete).not.toHaveBeenCalled();

    act(() => { vi.advanceTimersByTime((MAX_SECONDS - WARN_AT_SECONDS) * 1000); });
    expect(onComplete).toHaveBeenCalledOnce();
    const [blob, seconds, capped] = onComplete.mock.calls[0];
    expect(seconds).toBe(MAX_SECONDS);
    expect(capped).toBe(true);
    expect((blob as Blob).size).toBeGreaterThan(0);
    expect(FakeMediaRecorder.last?.state).toBe("inactive");
  });
});
