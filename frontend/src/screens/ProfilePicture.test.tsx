import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { cropOf } from "../components/PictureCrop";
import { aMe } from "../test/fixtures";
import { mockApi, renderRoute } from "../test/render";
import { Profile, ProfileData } from "./Profile";

// The crop itself needs a real canvas; here it is the step that hands back a
// cropped picture, so the flow around it can be tested.
vi.mock("../components/PictureCrop", async (original) => ({
  ...(await original<typeof import("../components/PictureCrop")>()),
  PictureCrop: ({ onDone, onCancel }: { onDone: (b: Blob) => void; onCancel: () => void }) => (
    <div role="dialog" aria-label="Crop your picture">
      <button onClick={() => onDone(new Blob(["cropped"], { type: "image/jpeg" }))}>
        Save picture</button>
      <button onClick={onCancel}>Cancel</button>
    </div>
  ),
}));

const MINE: ProfileData = {
  email: "casey@example.invalid", full_name: "Casey Field", role_label: "Associate",
  practice: "Executives Now", client_company_name: null, editable: true,
  picture_url: null, can_have_picture: true,
};
const WITH = { ...MINE, picture_url: "/api/people/m1/picture?v=abc" };

function show(profile: ProfileData = MINE, extra: Record<string, unknown> = {}) {
  const fetchMock = mockApi({
    "POST /api/me/profile/picture": WITH,
    "DELETE /api/me/profile/picture": MINE,
    "GET /api/me/profile": profile,
    "GET /api/me": aMe(),
    // Last, so a test's own answer replaces the default for the same route.
    ...extra,
  });
  vi.stubGlobal("fetch", fetchMock);
  renderRoute(<Profile />);
  return fetchMock;
}

const file = (name: string, type: string, bytes = 10) =>
  new File([new Uint8Array(bytes)], name, { type });

/** The profile picture (UI 3 spec §6). */
describe("the profile picture", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("shows initials and offers to add one when there is none", async () => {
    show();
    expect(await screen.findByRole("button", { name: "Add a picture" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Remove picture" })).not.toBeInTheDocument();
    expect(document.querySelector("img.avatar")).toBeNull();
    expect(screen.getByText(/your initials are shown/)).toBeInTheDocument();
  });

  it("crops, uploads the cropped picture, and then shows it", async () => {
    const user = userEvent.setup();
    const fetchMock = show();
    await screen.findByRole("button", { name: "Add a picture" });

    await user.upload(screen.getByLabelText("Choose a picture"), file("me.png", "image/png"));
    await user.click(await screen.findByRole("button", { name: "Save picture" }));

    await waitFor(() => expect(document.querySelector("img.avatar"))
      .toHaveAttribute("src", "/api/people/m1/picture?v=abc"));
    expect(fetchMock.calls.some(
      (c) => c.method === "POST" && c.url === "/api/me/profile/picture")).toBe(true);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Change picture" })).toBeInTheDocument();
  });

  it.each([
    ["me.gif", "image/gif", 10, "Use a JPEG, PNG or WebP picture."],
    ["me.svg", "image/svg+xml", 10, "Use a JPEG, PNG or WebP picture."],
    ["big.jpg", "image/jpeg", 5 * 1024 * 1024 + 1, /the limit is 5 MB/],
  ] as const)("refuses %s before anything is sent", async (name, type, bytes, message) => {
    // applyAccept off: a person can still drop any file on the control.
    const user = userEvent.setup({ applyAccept: false });
    const fetchMock = show();
    await screen.findByRole("button", { name: "Add a picture" });

    await user.upload(screen.getByLabelText("Choose a picture"), file(name, type, bytes));

    expect(await screen.findByText(message)).toBeInTheDocument();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(fetchMock.calls.some((c) => c.method === "POST")).toBe(false);
  });

  it("shows the server's refusal when the upload is turned down", async () => {
    const user = userEvent.setup();
    show(MINE, { "POST /api/me/profile/picture": () => ({
      status: 400, body: { picture: "Use a JPEG, PNG or WebP picture." } }) });
    await screen.findByRole("button", { name: "Add a picture" });

    await user.upload(screen.getByLabelText("Choose a picture"), file("me.png", "image/png"));
    await user.click(await screen.findByRole("button", { name: "Save picture" }));

    expect(await screen.findByText("Use a JPEG, PNG or WebP picture.")).toBeInTheDocument();
    expect(document.querySelector("img.avatar")).toBeNull();
  });

  it("removes the picture and goes back to initials", async () => {
    const user = userEvent.setup();
    const fetchMock = show(WITH);
    await user.click(await screen.findByRole("button", { name: "Remove picture" }));

    await waitFor(() => expect(document.querySelector("img.avatar")).toBeNull());
    expect(fetchMock.calls.some((c) => c.method === "DELETE")).toBe(true);
  });

  it("can be seen and not changed while acting as the person", async () => {
    show({ ...WITH, editable: false });
    await screen.findByLabelText("Full name");
    expect(document.querySelector("img.avatar")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /picture/ })).not.toBeInTheDocument();
  });

  it("is not offered where no practice holds it", async () => {
    show({ ...MINE, practice: null, role_label: null, can_have_picture: false });
    await screen.findByLabelText("Full name");
    expect(screen.queryByText("Your picture")).not.toBeInTheDocument();
  });
});

describe("the top bar's picture", () => {
  beforeEach(() => {
    vi.unstubAllGlobals();
    try { localStorage.clear(); } catch { /* private window */ }
  });

  it.each([
    ["/api/people/m1/picture?v=abc", true], [null, false],
  ] as const)("shows the picture when there is one, initials when not (%s)", async (url, has) => {
    const { App } = await import("../App");
    vi.stubGlobal("fetch", mockApi({
      "GET /api/me": aMe({ picture_url: url }),
      "GET /api/branding": { display_name: "Executives Now", product_name: "Execs NOW HQ",
                             logo_url: "", palette: null },
      "GET /api/": [],
    }));
    renderRoute(<App />, { path: "*", route: "/tasks" });
    const button = await screen.findByRole("button", { name: /Your account/ });
    const picture = button.querySelector("img.avatar");
    expect(!!picture).toBe(has);
    if (has) expect(picture).toHaveAttribute("src", url);
    else expect(button).toHaveTextContent("BB");
  });
});

describe("the crop", () => {
  it("is the largest centered square at zoom 1", () => {
    expect(cropOf(600, 400, 1, { x: 300, y: 200 })).toEqual({ x: 100, y: 0, size: 400 });
    expect(cropOf(400, 600, 1, { x: 200, y: 300 })).toEqual({ x: 0, y: 100, size: 400 });
  });

  it("shrinks as you zoom in, around the same point", () => {
    expect(cropOf(600, 400, 2, { x: 300, y: 200 })).toEqual({ x: 200, y: 100, size: 200 });
  });

  it("never runs off the edge of the picture, however far it is dragged", () => {
    expect(cropOf(600, 400, 2, { x: -500, y: -500 })).toEqual({ x: 0, y: 0, size: 200 });
    expect(cropOf(600, 400, 2, { x: 9999, y: 9999 })).toEqual({ x: 400, y: 200, size: 200 });
  });

  it("holds the zoom between 1 and 4", () => {
    expect(cropOf(400, 400, 0.2, { x: 200, y: 200 }).size).toBe(400);
    expect(cropOf(400, 400, 50, { x: 200, y: 200 }).size).toBe(100);
  });
});
