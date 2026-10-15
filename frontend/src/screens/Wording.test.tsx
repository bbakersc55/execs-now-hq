import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_WORD_PAIRS, WordsProvider, makeWords, useWords } from "../lib/words";
import { mockApi, renderRoute } from "../test/render";
import { WordingSection } from "./Wording";

/** Settings → Branding → Wording (2026-10-15): what the practice calls its four levels. */

const ACTIONS = { ...DEFAULT_WORD_PAIRS, task: { singular: "action", plural: "actions" } };

describe("the words, as a sentence needs them", () => {
  it("has each form, with its article", () => {
    const w = makeWords({ goal: { singular: "OKR", plural: "OKRs" },
                          task: { singular: "action", plural: "actions" } });
    expect([w.task, w.Tasks, w.aTask, w.ATask, w.aGoal, w.Project, w.count(1, "task"),
            w.count(3, "task"), w.of("step", { plural: true, capital: true })])
      .toEqual(["action", "Actions", "an action", "An action", "an OKR", "Project",
                "1 action", "3 actions", "Steps"]);
  });

  it("are the defaults with no practice's words given", () => {
    function Shown() { const w = useWords(); return <p>{w.Tasks}</p>; }
    render(<Shown />);
    expect(screen.getByText("Tasks")).toBeInTheDocument();
    render(<WordsProvider pairs={ACTIONS}><Shown /></WordsProvider>);
    expect(screen.getByText("Actions")).toBeInTheDocument();
  });
});

describe("Settings → Branding → Wording", () => {
  beforeEach(() => vi.unstubAllGlobals());

  it("saves the four pairs and reads back how they sound together", async () => {
    const user = userEvent.setup();
    const fetchMock = mockApi({
      "GET /api/settings/words": { words: DEFAULT_WORD_PAIRS, defaults: DEFAULT_WORD_PAIRS },
      "PUT /api/settings/words": () => ({ body: { words: ACTIONS,
                                                  defaults: DEFAULT_WORD_PAIRS } }),
    });
    vi.stubGlobal("fetch", fetchMock);
    renderRoute(<WordingSection />);
    expect(await screen.findByRole("heading", { name: "Wording" })).toBeInTheDocument();
    const one = await screen.findByLabelText("Word for one task");
    await user.clear(one);
    await user.type(one, "action");
    await user.clear(screen.getByLabelText("Word for more than one task"));
    await user.type(screen.getByLabelText("Word for more than one task"), "actions");
    expect(screen.getByLabelText("How it reads")).toHaveTextContent(
      "Reads as: Goals hold projects, projects hold actions, and an action can have steps.");
    await user.click(screen.getByRole("button", { name: "Save the wording" }));
    await waitFor(() => expect(fetchMock.calls.find((c) => c.method === "PUT")?.body)
      .toEqual({ words: ACTIONS }));
    expect(await screen.findByText(/nothing else changed/)).toBeInTheDocument();
  });
});
