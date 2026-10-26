import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { BrowserNotifications, NoticesBell } from "./Notifications";
import { mockApi, renderRoute } from "../test/render";

const KINDS = [
  { key: "notice", label: "Notices from the pipeline's stage rules", on: true },
  { key: "mention", label: "Someone mentions you in a comment", on: true },
];
const STATE = { refusal: "", public_key: "BEl62iUYgUivxIkv69yViEuiBIa-Ib9-SkvMeAtA3LFgDzkrxZJjSgSnfckjBJuBkr3qBUYIHBQFLXYp5Nksh8U",
  browsers: 1, kinds: KINDS };

describe("the Notices list (2026-10-26)", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("counts the unread, opens the list, and a click marks it read and opens its page", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "POST /api/notify/notices/read/": { read: 1, unread: 0 },
      "GET /api/notify/notices/": { unread: 1, notices: [
        { id: "n1", kind: "mention", title: "Olive Owner mentioned you", text: "On “Count”: check this",
          url: "/tasks/t1", created_at: "2026-10-26T15:00:00Z", read: false },
        { id: "n2", kind: "notice", title: "Pipeline", text: "Call Dana back", url: "/contacts/c1",
          created_at: "2026-10-25T15:00:00Z", read: true }] },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<NoticesBell />, { path: "*", route: "/dashboard" });
    await user.click(await screen.findByRole("button", { name: "Notices, 1 unread" }));
    const panel = screen.getByRole("dialog", { name: "Notices" });
    expect(within(panel).getByText("Call Dana back")).toBeInTheDocument();
    await user.click(within(panel).getByText("Olive Owner mentioned you"));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({ ids: ["n1"] }));
    expect(screen.queryByRole("dialog", { name: "Notices" })).toBeNull();
  });
});

describe("Notify me in the browser (Profile)", () => {
  beforeEach(() => vi.unstubAllGlobals());
  afterEach(() => vi.unstubAllGlobals());

  it("says why it can't be had: a demo copy, or no keys", async () => {
    vi.stubGlobal("fetch", mockApi({ "GET /api/notify/push/": { ...STATE, browsers: 0,
      refusal: "Browser notifications are not part of a demo copy." } }));
    renderRoute(<BrowserNotifications editable />);
    expect(await screen.findByText("Browser notifications are not part of a demo copy.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Notify me in this browser/ })).toBeNull();
  });

  it("turns it on in this browser: asks permission, subscribes, and tells the server", async () => {
    const user = userEvent.setup();
    const subscription = { endpoint: "https://fcm.googleapis.com/fcm/send/abc",
      toJSON: () => ({ endpoint: "https://fcm.googleapis.com/fcm/send/abc", keys: { p256dh: "p", auth: "a" } }) };
    const reg = { pushManager: { getSubscription: vi.fn(async () => null), subscribe: vi.fn(async () => subscription) } };
    vi.stubGlobal("navigator", { ...navigator, serviceWorker: {
      getRegistration: vi.fn(async () => undefined), register: vi.fn(async () => reg), ready: Promise.resolve(reg) } });
    vi.stubGlobal("PushManager", function PushManager() {});
    vi.stubGlobal("Notification", { requestPermission: vi.fn(async () => "granted") });
    const fetchMock = mockApi({
      "POST /api/notify/push/subscribe/": { ...STATE },
      "GET /api/notify/push/": { ...STATE, browsers: 0 },
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<BrowserNotifications editable />);
    await user.click(await screen.findByRole("button", { name: "Notify me in this browser" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "POST")?.body).toEqual({
      endpoint: "https://fcm.googleapis.com/fcm/send/abc", keys: { p256dh: "p", auth: "a" } }));
    expect(reg.pushManager.subscribe).toHaveBeenCalledWith(expect.objectContaining({ userVisibleOnly: true }));
    expect(await screen.findByText("On in this browser.")).toBeInTheDocument();
  });

  it("every kind is a switch of its own", async () => {
    const user = userEvent.setup();
    vi.stubGlobal("PushManager", function PushManager() {});
    vi.stubGlobal("Notification", { requestPermission: vi.fn() });
    vi.stubGlobal("navigator", { ...navigator, serviceWorker: { getRegistration: vi.fn(async () => undefined) } });
    const fetchMock = mockApi({
      "PUT /api/notify/push/": { ...STATE, kinds: [KINDS[0], { ...KINDS[1], on: false }] },
      "GET /api/notify/push/": STATE,
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<BrowserNotifications editable />);
    await user.click(await screen.findByLabelText("Someone mentions you in a comment"));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body).toEqual({ kinds: ["notice"] }));
    expect(screen.getByLabelText("Someone mentions you in a comment")).not.toBeChecked();
  });

  it("while acting as someone, it can't be changed", async () => {
    vi.stubGlobal("PushManager", function PushManager() {});
    vi.stubGlobal("Notification", { requestPermission: vi.fn() });
    vi.stubGlobal("navigator", { ...navigator, serviceWorker: { getRegistration: vi.fn(async () => undefined) } });
    vi.stubGlobal("fetch", mockApi({ "GET /api/notify/push/": STATE }));
    renderRoute(<BrowserNotifications editable={false} />);
    expect(await screen.findByText(/aren't yours to change/)).toBeInTheDocument();
  });
});
