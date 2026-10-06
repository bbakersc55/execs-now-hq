import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import {
  DigestSchedule, DigestSchedulePrompt, DigestSettings, draftGapHours, hourLabel,
  outsideWorkingHours, resultSentence,
} from "./DigestSettings";

const NAMES = ["", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"];
/** A new practice: drafted Thursday 8:00 AM, sent Friday 8:00 AM. */
const NEW: DigestSchedule = {
  draft_day: 4, draft_day_name: "Thursday", draft_hour: 8,
  day: 5, day_name: "Friday", hour: 8,
  timezone: "America/Denver", outside_working_hours: false, confirmed: false,
};
const times = (draft_day: number, draft_hour: number, day: number, hour: number) =>
  ({ draft_day, draft_hour, day, hour });

function stub(now: DigestSchedule = NEW) {
  const fetchMock = mockApi({
    "POST /api/digests/schedule/confirm/": { ...now, confirmed: true },
    "PATCH /api/digests/schedule/": (body: unknown) => {
      const sent = body as DigestSchedule;
      return { body: { ...sent, day_name: NAMES[sent.day],
                       draft_day_name: NAMES[sent.draft_day], confirmed: true } };
    },
    "GET /api/digests/schedule/": now,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

/** Draft on and Send on (docs/digest_schedule.md §3). */
describe("Settings → Digests", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("says in one sentence what the two settings add up to", () => {
    expect(resultSentence(times(5, 15, 1, 8))).toBe(
      "Work finished by Friday 3:00 PM is included. Approve any time until Monday 8:00 AM, "
      + "when approved digests are sent.");
    expect(hourLabel(0)).toBe("12:00 AM");
    expect(hourLabel(12)).toBe("12:00 PM");
  });

  it.each([
    [times(4, 8, 5, 8), 24, false],     // the default
    [times(5, 15, 1, 8), 65, false],    // Friday afternoon to Monday morning
    [times(7, 8, 1, 8), 24, true],      // Sunday to Monday 8 AM
    [times(5, 17, 1, 9), 64, true],     // the whole weekend
    [times(5, 17, 1, 10), 65, false],   // an hour of Monday morning counts
    [times(5, 8, 5, 8), 0, true],       // the same moment: no window at all
  ] as const)("knows the approval window and whether it has working hours (%#)",
    (t, gap, outside) => {
      expect(draftGapHours(t)).toBe(gap);
      expect(outsideWorkingHours(t)).toBe(outside);
    });

  it("shows Draft on, Send on and the time zone in one card", async () => {
    stub();
    renderRoute(<DigestSettings />);

    expect(await screen.findByLabelText("Draft day")).toHaveValue("4");
    expect(screen.getByLabelText("Draft time")).toHaveValue("8");
    expect(screen.getByLabelText("Send day")).toHaveValue("5");
    expect(screen.getByLabelText("Send time")).toHaveValue("8");
    expect(screen.getByLabelText("Practice time zone")).toHaveValue("America/Denver");
    expect(screen.getByLabelText("What this schedule does")).toHaveTextContent(
      "Work finished by Thursday 8:00 AM is included. Approve any time until Friday 8:00 AM");
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.queryByText(/outside working hours/)).not.toBeInTheDocument();
  });

  it("sets Friday 3:00 PM and Monday 8:00 AM, and the sentence follows as it is set", async () => {
    const user = userEvent.setup();
    const fetchMock = stub();
    renderRoute(<DigestSettings />);

    await user.selectOptions(await screen.findByLabelText("Send day"), "1");
    await user.selectOptions(screen.getByLabelText("Draft day"), "5");
    await user.selectOptions(screen.getByLabelText("Draft time"), "15");
    expect(screen.getByLabelText("What this schedule does")).toHaveTextContent(
      "Work finished by Friday 3:00 PM is included. Approve any time until Monday 8:00 AM");
    expect(screen.queryByText(/outside working hours/)).not.toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));

    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PATCH")?.body)
      .toEqual({ draft_day: 5, draft_hour: 15, day: 1, hour: 8, timezone: "America/Denver" }));
    expect(await screen.findByText("Saved.")).toBeInTheDocument();
  });

  it("warns gently, and still saves, when nobody would be at work to approve", async () => {
    const user = userEvent.setup();
    const fetchMock = stub();
    renderRoute(<DigestSettings />);

    // What a fixed 24 hours gave a Monday send: Sunday to Monday 8:00 AM.
    await user.selectOptions(await screen.findByLabelText("Send day"), "1");
    await user.selectOptions(screen.getByLabelText("Draft day"), "7");

    expect(screen.getByText(/All of the time to approve these falls outside working hours/))
      .toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(fetchMock.calls.some((c) => c.method === "PATCH")).toBe(true));
  });

  it("refuses a draft time that leaves no time to approve", async () => {
    const user = userEvent.setup();
    const fetchMock = stub();
    renderRoute(<DigestSettings />);

    await user.selectOptions(await screen.findByLabelText("Draft day"), "5");   // same as Send on

    expect(screen.getByText(/Draft on must be at least 2 hours before Send on/))
      .toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(fetchMock.calls.some((c) => c.method === "PATCH")).toBe(false);
  });

  it("is plain about each cadence and about approval", async () => {
    stub({ ...NEW, draft_day: 5, draft_hour: 15, day: 1 });
    renderRoute(<DigestSettings />);
    const card = (await screen.findByRole("heading", { name: "Digest day and time" }))
      .closest("section")!;

    expect(card).toHaveTextContent(/Weekly digests are written at Draft on and sent at Send on/);
    expect(card).toHaveTextContent(/first Monday of the month, written on the Friday before it/);
    expect(card).toHaveTextContent(/every update is not on this schedule/);
    expect(card).toHaveTextContent(/One already waiting on the Digests screen keeps the time/);
    expect(card).toHaveTextContent(/Every digest still waits for the practice owner or an associate to approve it/);
    expect(card).toHaveTextContent(/Reminders by email go to the practice owner, and to each associate for their own clients/);
    expect(card).toHaveTextContent(/never include its text/);
  });

  it("offers no switch for holding digests", async () => {
    stub();
    renderRoute(<DigestSettings />);
    await screen.findByLabelText("Draft day");
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

  it("asks the practice owner once, in the new wording, and Keep answers it", async () => {
    const user = userEvent.setup();
    const fetchMock = stub();
    renderRoute(<DigestSchedulePrompt me={aMe({ role: "FF" })} />);

    const card = (await screen.findByRole("heading", { name: "When should your digests go out?" }))
      .closest("section")!;
    expect(card).toHaveTextContent("written on Thursdays at 8:00 AM");
    expect(card).toHaveTextContent("sent on Fridays at 8:00 AM");
    expect(card).toHaveTextContent("Work finished by Thursday 8:00 AM is included.");
    expect(within(card).getByRole("link", { name: "Change the days or times" }))
      .toHaveAttribute("href", "/settings/digests");

    await user.click(within(card).getByRole("button", { name: "Keep this schedule" }));

    await waitFor(() => expect(
      screen.queryByRole("heading", { name: "When should your digests go out?" }))
      .not.toBeInTheDocument());
    expect(fetchMock.calls.some((c) => c.method === "POST"
      && c.url === "/api/digests/schedule/confirm/")).toBe(true);
  });

  it("carries the working-hours warning when it applies", async () => {
    stub({ ...NEW, draft_day: 7, draft_day_name: "Sunday", day: 1, day_name: "Monday",
           outside_working_hours: true });
    renderRoute(<DigestSchedulePrompt me={aMe({ role: "FF" })} />);
    expect(await screen.findByText(/outside working hours/)).toBeInTheDocument();
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
