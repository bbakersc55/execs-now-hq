import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import {
  DigestSchedule, DigestSchedulePrompt, DigestSettings, hourLabel, scheduleSentence,
} from "./DigestSettings";

const NEW: DigestSchedule = { day: 5, day_name: "Friday", hour: 8,
                              timezone: "America/Denver", confirmed: false };
const NAMES = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];

function stub(now: DigestSchedule = NEW) {
  const fetchMock = mockApi({
    "POST /api/digests/schedule/confirm/": { ...now, confirmed: true },
    "PATCH /api/digests/schedule/": (body: unknown) => {
      const sent = body as { day: number; hour: number; timezone: string };
      return { body: { ...sent, day_name: NAMES[sent.day], confirmed: true } };
    },
    "GET /api/digests/schedule/": now,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Digest day and time (beta feedback, 2026-10-05, item E). */
describe("Settings → Digests", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says when digests go out, in words", () => {
    expect(scheduleSentence(NEW)).toBe("Fridays at 8:00 AM Mountain (America/Denver)");
    expect(hourLabel(0)).toBe("12:00 AM");
    expect(hourLabel(12)).toBe("12:00 PM");
    expect(hourLabel(15)).toBe("3:00 PM");
  });

  it("shows the day, time and time zone in one control", async () => {
    stub();
    renderRoute(<DigestSettings />);

    expect(await screen.findByLabelText("Digest day")).toHaveValue("5");
    expect(screen.getByLabelText("Digest time")).toHaveValue("8");
    expect(screen.getByLabelText("Practice time zone")).toHaveValue("America/Denver");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
  });

  it("saves a new day, time and time zone together", async () => {
    const user = userEvent.setup();
    const fetchMock = stub();
    renderRoute(<DigestSettings />);

    await user.selectOptions(await screen.findByLabelText("Digest day"), "4");
    await user.selectOptions(screen.getByLabelText("Digest time"), "14");
    await user.selectOptions(screen.getByLabelText("Practice time zone"), "America/Chicago");
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toEqual({ day: 4, hour: 14, timezone: "America/Chicago" }));
    expect(await screen.findByText(
      "Saved. Digests now go out on Thursdays at 2:00 PM Central (America/Chicago)."))
      .toBeInTheDocument();
  });

  it("is plain about what the schedule does and does not govern", async () => {
    stub();
    renderRoute(<DigestSettings />);
    const card = (await screen.findByRole("heading", { name: "Digest day and time" }))
      .closest("section")!;

    expect(card).toHaveTextContent(/written 24 hours before this time/);
    expect(card).toHaveTextContent(/first Friday of the month/);
    expect(card).toHaveTextContent(/every update is not on this schedule/);
    expect(card).toHaveTextContent(/One already waiting on the Digests screen keeps the time/);
    expect(card).toHaveTextContent(/Every digest still waits for the practice owner or an associate to approve it/);
  });

  it("offers no switch for holding digests", async () => {
    stub();
    renderRoute(<DigestSettings />);
    await screen.findByLabelText("Digest day");
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(document.body).not.toHaveTextContent(/hold_all_digests/);
  });

  it("keeps a time zone that is not in the browser's list", async () => {
    stub({ ...NEW, timezone: "Etc/GMT+12" });
    renderRoute(<DigestSettings />);
    expect(await screen.findByLabelText("Practice time zone")).toHaveValue("Etc/GMT+12");
  });
});

describe("the one-time prompt on Digests", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("asks the practice owner once, and Keep answers it", async () => {
    const user = userEvent.setup();
    const fetchMock = stub();
    renderRoute(<DigestSchedulePrompt me={aMe({ role: "FF" })} />);

    const card = (await screen.findByRole("heading", { name: "When should your digests go out?" }))
      .closest("section")!;
    expect(card).toHaveTextContent("Fridays at 8:00 AM Mountain (America/Denver)");
    expect(within(card).getByRole("link", { name: "Change the day or time" }))
      .toHaveAttribute("href", "/settings/digests");

    await user.click(within(card).getByRole("button", { name: "Keep Fridays at 8:00 AM" }));

    await waitFor(() => expect(
      screen.queryByRole("heading", { name: "When should your digests go out?" }))
      .not.toBeInTheDocument());
    expect(fetchMock.calls.some((c) => c.method === "POST"
      && c.url === "/api/digests/schedule/confirm/")).toBe(true);
  });

  it("does not ask again once it has been kept or changed", async () => {
    stub({ ...NEW, confirmed: true });
    const view = renderRoute(<DigestSchedulePrompt me={aMe({ role: "FF" })} />);
    await waitFor(() => expect(vi.mocked(fetch)).toHaveBeenCalled());
    expect(view.container).toBeEmptyDOMElement();
  });

  it.each(["CF", "VA"] as const)("never asks %s, and does not fetch for them", (role) => {
    const fetchMock = stub();
    const view = renderRoute(<DigestSchedulePrompt me={aMe({ role })} />);
    expect(view.container).toBeEmptyDOMElement();
    expect(fetchMock.calls).toEqual([]);
  });
});
