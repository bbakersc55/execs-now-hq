import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { RichText, insertMergeField } from "./RichText";

/** The editor in a parent that holds its value, as every screen does. */
function Harness({ start, seen }: { start: string; seen: string[] }) {
  const [value, setValue] = useState(start);
  return <RichText label="Email body" value={value}
    onChange={(html) => { seen.push(html); setValue(html); }} />;
}

function caretAtEnd(node: Node) {
  const range = document.createRange();
  range.selectNodeContents(node);
  range.collapse(false);
  const selection = getSelection()!;
  selection.removeAllRanges();
  selection.addRange(range);
}

/** Owner, 2026-10-19: a merge field is a chip the caret sits after, Enter
 *  leaves on its line, and Backspace takes whole. (Enter and real typing are
 *  checked in headless Chrome; jsdom has no editing.) */
describe("merge fields in the rich editor", () => {
  it("shows a stored token as a chip and stores the chip as its token", () => {
    const seen: string[] = [];
    render(<Harness start="<p>Hi {FirstName}, from {Company}.</p>" seen={seen} />);
    const editor = screen.getByRole("textbox", { name: "Email body" });
    const chips = editor.querySelectorAll<HTMLElement>("[data-merge]");
    expect([...chips].map((c) => c.dataset.merge)).toEqual(["{FirstName}", "{Company}"]);
    expect(chips[0].getAttribute("contenteditable")).toBe("false");
    fireEvent.input(editor);
    expect(seen.at(-1)).toBe("<p>Hi {FirstName}, from {Company}.</p>");
  });

  it("puts the caret right after an inserted chip, at the end of a line too", () => {
    const seen: string[] = [];
    render(<Harness start="<p>Hi there, </p>" seen={seen} />);
    const editor = screen.getByRole("textbox", { name: "Email body" });
    caretAtEnd(editor.querySelector("p")!);
    insertMergeField("{FirstName}");
    const chip = editor.querySelector<HTMLElement>("[data-merge]")!;
    const caret = getSelection()!.getRangeAt(0);
    // The caret is in the placeholder that follows the chip, past it.
    expect(caret.startContainer).toBe(chip.nextSibling);
    expect(caret.startOffset).toBe(1);
    expect(seen.at(-1)).toBe("<p>Hi there, {FirstName}</p>");
    // What the editor sent up is not written back over it (that moved the caret).
    expect(editor.querySelector("[data-merge]")).toBe(chip);
  });

  it("takes a chip whole with one Backspace, and leaves other text alone", () => {
    const seen: string[] = [];
    render(<Harness start="<p>Hi {FirstName}</p><p>Thanks</p>" seen={seen} />);
    const editor = screen.getByRole("textbox", { name: "Email body" });
    caretAtEnd(editor.querySelector("p")!);
    fireEvent.keyDown(editor, { key: "Backspace" });
    expect(editor.querySelectorAll("[data-merge]")).toHaveLength(0);
    expect(seen.at(-1)).toBe("<p>Hi </p><p>Thanks</p>");
    // Not after a chip: the browser's own Backspace, untouched.
    caretAtEnd(editor.querySelectorAll("p")[1]);
    const press = fireEvent.keyDown(editor, { key: "Backspace" });
    expect(press).toBe(true);
  });

  it("puts a token as plain text where there is no rich editor", () => {
    const box = document.createElement("textarea");
    document.body.append(box);
    box.focus();
    const calls: string[] = [];
    const original = document.execCommand;
    document.execCommand = ((_c: string, _u?: boolean, v?: string) => {
      calls.push(v ?? ""); return true; }) as typeof document.execCommand;
    getSelection()!.removeAllRanges();
    insertMergeField("{Company}");
    document.execCommand = original;
    expect(calls).toEqual(["{Company}"]);
    box.remove();
  });
});

/** Owner, 2026-10-20: the template library's editor is the same chips over
 *  plain text. */
describe("the plain-text chip editor", () => {
  function Plain({ start, seen }: { start: string; seen: string[] }) {
    const [value, setValue] = useState(start);
    return <RichText plain label="Template body" value={value}
      onChange={(text) => { seen.push(text); setValue(text); }} />;
  }

  it("shows plain text with chips and hands back plain text", () => {
    const seen: string[] = [];
    render(<Plain start={"Hi {FirstName},\n\n{PracticeNews}\nThanks & bye."} seen={seen} />);
    const editor = screen.getByRole("textbox", { name: "Template body" });
    expect([...editor.querySelectorAll<HTMLElement>("[data-merge]")].map((c) => c.dataset.merge))
      .toEqual(["{FirstName}", "{PracticeNews}"]);
    expect(editor.querySelectorAll("p")).toHaveLength(2);
    expect(screen.queryByRole("button", { name: "B" })).not.toBeInTheDocument();
    fireEvent.input(editor);
    expect(seen.at(-1)).toBe("Hi {FirstName},\n\n{PracticeNews}\nThanks & bye.");
  });

  it("drops formatting typed by habit", () => {
    const seen: string[] = [];
    render(<Plain start="Hi" seen={seen} />);
    const editor = screen.getByRole("textbox", { name: "Template body" });
    editor.innerHTML = "<p>Hi <b>{FirstName}</b></p>";
    fireEvent.input(editor);
    expect(seen.at(-1)).toBe("Hi {FirstName}");
  });
});
