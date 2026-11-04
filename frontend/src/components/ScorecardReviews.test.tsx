import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { GoogleReviewsCard, ReviewsCard, ReviewsFeedModal } from "./ScorecardReviews";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";

/** Google reviews (docs/google_reviews_feed.md): the company page's cards and a KPI's measure. */

const CONNECTED = {
  connected: true, demo: false, google_email: "manager@stark.example", account: "accounts/1",
  account_label: "Stark Tool & Die", location: "locations/2", location_title: "Stark Tool & Die, Denver",
  chosen: true, average_rating: 4.6, total_review_count: 31, not_approved: false, not_approved_text: "",
  checked_at: null, check_ok: null, check_detail: "", last_read_at: "2026-11-04T06:30:00Z",
  last_error: "", stored: 31,
};
const MEASURES = [
  { key: "new_reviews", label: "New reviews", kind: "count", star: false },
  { key: "reviews_by_star", label: "New reviews with a given number of stars", kind: "count", star: true },
];

beforeEach(() => vi.unstubAllGlobals());

describe("the Google Business Profile card", () => {
  it("starts the Google sign-in for the practice owner", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign });
    const fetchMock = mockApi({
      "POST /api/scorecard/reviews/connection/start/": { url: "https://accounts.google.com/o/oauth2/v2/auth?x=1" },
      "/api/scorecard/reviews/connection/": { connected: false, demo: false },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<GoogleReviewsCard me={aMe({ role: "FF" })} companyId="c1" />);
    await userEvent.click(await screen.findByRole("button", { name: "Sign in with Google" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("https://accounts.google.com/o/oauth2/v2/auth?x=1"));
    expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({ company: "c1" });
  });

  it("chooses the account and location from Google's lists", async () => {
    const fetchMock = mockApi({
      "/api/scorecard/reviews/connection/choices/": { error: "", not_approved: false,
        accounts: [{ name: "accounts/1", label: "Stark Tool & Die", type: "LOCATION_GROUP" }],
        locations: [{ name: "locations/2", title: "Stark Tool & Die, Denver", address: "1 Forge Way, Denver" }] },
      "PUT /api/scorecard/reviews/connection/": CONNECTED,
      "/api/scorecard/reviews/connection/": { ...CONNECTED, chosen: false, location: "", location_title: "",
        account: "" },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<GoogleReviewsCard me={aMe({ role: "FF" })} companyId="c1" />,
      { route: "/?reviews_connected=manager%40stark.example" });
    expect(await screen.findByText(/Signed in with Google as manager@stark.example/)).toBeInTheDocument();
    // One account: chosen for them; then the location.
    await waitFor(() => expect(screen.getByLabelText("Account")).toHaveValue("accounts/1"));
    await userEvent.selectOptions(await screen.findByLabelText("Location"), "locations/2");
    await userEvent.click(screen.getByRole("button", { name: "Use this location" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual({
      company: "c1", account: "accounts/1", location: "locations/2", account_label: "Stark Tool & Die",
      location_title: "Stark Tool & Die, Denver" }));
  });

  it("says plainly when Google hasn't approved API access yet, and keeps the connection", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/scorecard/reviews/connection/": { ...CONNECTED,
      not_approved: true, last_error: "Google hasn't approved…",
      not_approved_text: "Google hasn't approved this app's access to Business Profile reviews yet. "
        + "The connection stays, and reviews are read once Google approves it." } }));
    renderRoute(<GoogleReviewsCard me={aMe({ role: "FF" })} companyId="c1" />);
    expect(await screen.findByLabelText("Google approval")).toHaveTextContent(
      "Google hasn't approved this app's access to Business Profile reviews yet.");
    expect(screen.getByText("Stark Tool & Die, Denver")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Disconnect" })).toBeInTheDocument();
  });

  it("shows an associate the connection but no controls", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/scorecard/reviews/connection/": CONNECTED }));
    renderRoute(<GoogleReviewsCard me={aMe({ role: "CF" })} companyId="c1" />);
    expect(await screen.findByText(/4.6 average from 31 reviews/)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Test connection" })).toBeNull();
  });
});

describe("the Reviews card", () => {
  it("lists the latest reviews with stars, date and replied or not", async () => {
    vi.stubGlobal("fetch", mockApi({ "/api/scorecard/reviews/latest/": { ...CONNECTED, reviews: [
      { id: "r2", stars: 3, comment: "Rework on two parts.", reviewer: "Pat", created_at: "2026-10-30T10:00:00Z",
        replied: false, reply_at: null },
      { id: "r1", stars: 5, comment: "Early delivery.", reviewer: "Ellen R.", created_at: "2026-10-01T10:00:00Z",
        replied: true, reply_at: "2026-10-02T10:00:00Z" }] } }));
    renderRoute(<ReviewsCard companyId="c1" />);
    const list = await screen.findByRole("list", { name: "Latest Google reviews" });
    const [first, second] = within(list).getAllByRole("listitem");
    expect(within(first).getByLabelText("3 stars")).toBeInTheDocument();
    expect(within(first).getByText("Not replied")).toBeInTheDocument();
    expect(within(first).getByText("October 30, 2026")).toBeInTheDocument();
    expect(within(second).getByText("Replied")).toBeInTheDocument();
  });

  it("is not shown before a location is chosen", async () => {
    const fetchMock = mockApi({ "/api/scorecard/reviews/latest/": { connected: false, demo: false, reviews: [] } });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<ReviewsCard companyId="c1" />);
    await waitFor(() => expect(fetchMock.calls.length).toBe(1));
    expect(screen.queryByText("Google reviews")).toBeNull();
  });
});

describe("a KPI's Google reviews measure", () => {
  it("offers the menu at once and saves a measure with its star", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "PUT /api/scorecard/reviews/feed/": { feed: {}, run: { ok: true, new: 13 } },
      "/api/scorecard/reviews/feed/": { kpi: { id: "k1", name: "One-star reviews", kind: "count",
        per_person: false, read_open_default: false }, connected: true, location_title: "Stark Tool & Die, Denver",
        measures: MEASURES, feed: null },
    });
    vi.stubGlobal("fetch", fetchMock);
    const onSaved = vi.fn();
    renderRoute(<ReviewsFeedModal companyId="c1" kpiId="k1" onClose={() => {}} onSaved={onSaved} />);
    const picker = await screen.findByLabelText("Measure");
    picker.focus();
    await user.keyboard("{ArrowDown}");
    await user.selectOptions(picker, "reviews_by_star");
    await user.selectOptions(screen.getByLabelText("Stars"), "1");
    await user.click(screen.getByRole("button", { name: "Save the measure" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual({
      company: "c1", kpi: "k1", measure: "reviews_by_star", star: 1, read_open: false }));
    expect(onSaved).toHaveBeenCalledWith("One-star reviews now reads from Google reviews: 13 readings for past periods.");
  });
});
