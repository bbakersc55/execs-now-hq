import { useEffect, useRef } from "react";

/**
 * A small contentEditable editor producing clean HTML plus a plain-text
 * alternative (FR-1.15e).
 *
 * Deliberately not a library: the formatting an email actually needs is bold,
 * italic, links and lists, and every heavyweight editor ships a stylesheet and
 * a paste pipeline that put `<span style>` soup into the body. `sanitize` below
 * is what keeps the HTML clean — paste is forced through plain text, and the
 * output is filtered to an allow-list of tags.
 */
const ALLOWED = new Set(["B", "STRONG", "I", "EM", "U", "A", "P", "BR", "UL", "OL", "LI"]);

export function sanitize(html: string): string {
  const host = document.createElement("div");
  host.innerHTML = html;
  const walk = (node: Element) => {
    [...node.children].forEach((child) => {
      walk(child);
      if (!ALLOWED.has(child.tagName)) {
        child.replaceWith(...child.childNodes);
        return;
      }
      [...child.attributes].forEach((attr) => {
        const keep = child.tagName === "A" && attr.name === "href"
          && /^(https?:|mailto:)/i.test(attr.value);
        if (!keep) child.removeAttribute(attr.name);
      });
    });
  };
  walk(host);
  return host.innerHTML;
}

/** The plain-text alternative every message carries alongside its HTML. */
export function toPlainText(html: string): string {
  const host = document.createElement("div");
  host.innerHTML = html
    .replace(/<\/p>/gi, "\n\n")
    .replace(/<\/(li|ul|ol)>/gi, "\n")
    .replace(/<br\s*\/?>/gi, "\n");
  return (host.textContent ?? "").replace(/\n{3,}/g, "\n\n").trim();
}

// ------------------------------------------------------------ merge fields
//
// A merge field ({FirstName}, {Company}, ...) shows as a chip: one unit the
// caret goes after, Enter leaves on its line, and Backspace takes whole. In the
// stored HTML it is the plain token, which is what the server merges.

const TOKEN = /\{[A-Za-z][A-Za-z_]*\}/g;
const ZWSP = "\u200B";

function makeChip(token: string): HTMLSpanElement {
  const chip = document.createElement("span");
  chip.className = "merge-chip";
  chip.setAttribute("contenteditable", "false");
  chip.dataset.merge = token;
  chip.textContent = token;
  return chip;
}

/** The stored HTML as the editor shows it: each token a chip. */
function toEditor(html: string): string {
  const host = document.createElement("div");
  host.innerHTML = html;
  const walker = document.createTreeWalker(host, NodeFilter.SHOW_TEXT);
  const texts: Text[] = [];
  while (walker.nextNode()) texts.push(walker.currentNode as Text);
  for (const text of texts) {
    const value = text.data;
    if (!TOKEN.test(value)) continue;
    TOKEN.lastIndex = 0;
    const parts = document.createDocumentFragment();
    let at = 0;
    for (const match of value.matchAll(TOKEN)) {
      parts.append(value.slice(at, match.index), makeChip(match[0]));
      at = (match.index ?? 0) + match[0].length;
    }
    parts.append(value.slice(at));
    text.replaceWith(parts);
  }
  return host.innerHTML;
}

/** What the editor holds, as stored HTML: chips back to their tokens, the
 *  caret's placeholders gone, then the usual clean-up. */
function fromEditor(root: HTMLElement): string {
  const copy = root.cloneNode(true) as HTMLElement;
  copy.querySelectorAll<HTMLElement>("[data-merge]").forEach((chip) => {
    chip.replaceWith(document.createTextNode(chip.dataset.merge ?? ""));
  });
  return sanitize(copy.innerHTML.split(ZWSP).join(""));
}

/**
 * Insert a merge field at the caret. In a rich editor it is a chip with the
 * caret right after it (a zero-width placeholder holds the caret's place, so
 * a chip at the end of a line keeps the caret after it, not before); in a
 * plain text box, the token as text.
 */
export function insertMergeField(token: string) {
  const selection = window.getSelection();
  const range = selection && selection.rangeCount ? selection.getRangeAt(0) : null;
  const start = range?.startContainer;
  const host = (start instanceof Element ? start : start?.parentElement)
    ?.closest<HTMLElement>(".richtext");
  if (!range || !host || !selection) {
    document.execCommand("insertText", false, token);
    return;
  }
  range.deleteContents();
  const chip = makeChip(token);
  const after = document.createTextNode(ZWSP);
  range.insertNode(after);
  range.insertNode(chip);
  const caret = document.createRange();
  caret.setStart(after, 1);
  caret.collapse(true);
  selection.removeAllRanges();
  selection.addRange(caret);
  host.dispatchEvent(new Event("input", { bubbles: true }));
}

/** The chip just before a collapsed caret, looking past placeholders. */
function chipBefore(range: Range): { chip: HTMLElement; text: Text | null } | null {
  let node: Node | null = range.startContainer;
  let offset = range.startOffset;
  let text: Text | null = null;
  if (node.nodeType === Node.TEXT_NODE) {
    text = node as Text;
    if (text.data.slice(0, offset).split(ZWSP).join("") !== "") return null;
    node = text.previousSibling;
  } else {
    node = node.childNodes[offset - 1] ?? null;
    while (node && node.nodeType === Node.TEXT_NODE
           && (node as Text).data.split(ZWSP).join("") === "") {
      node = node.previousSibling;
    }
  }
  return node instanceof HTMLElement && node.dataset.merge !== undefined
    ? { chip: node, text } : null;
}

export function RichText({ value, onChange, label }: {
  value: string;
  onChange: (html: string, text: string) => void;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // What this editor last sent up. A value that is only that coming back is
  // not written into the DOM: rewriting it moves the caret to the start, which
  // is how typing used to land before a merge field.
  const sent = useRef<string | null>(null);

  useEffect(() => {
    if (!ref.current || value === sent.current) return;
    const shown = toEditor(value);
    if (ref.current.innerHTML !== shown) ref.current.innerHTML = shown;
  }, [value]);

  function emit() {
    if (!ref.current) return;
    const html = fromEditor(ref.current);
    sent.current = html;
    onChange(html, toPlainText(html));
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLDivElement>) {
    if (e.key !== "Backspace") return;
    const selection = window.getSelection();
    if (!selection || !selection.rangeCount || !selection.isCollapsed) return;
    const found = chipBefore(selection.getRangeAt(0));
    if (!found) return;
    // The chip goes as one unit, with the placeholder that held the caret.
    e.preventDefault();
    const { chip, text } = found;
    const caret = document.createRange();
    if (text) {
      text.data = text.data.split(ZWSP).join("");
      caret.setStart(text, 0);
    } else {
      caret.setStartBefore(chip);
    }
    caret.collapse(true);
    chip.remove();
    selection.removeAllRanges();
    selection.addRange(caret);
    emit();
  }

  function cmd(command: string) {
    document.execCommand(command, false);
    ref.current?.focus();
    emit();
  }

  return (
    <div>
      <div className="row" style={{ marginBottom: ".3rem" }}>
        {[["bold", "B"], ["italic", "I"], ["insertUnorderedList", "• List"]].map(
          ([command, text]) => (
            <button key={command} type="button" className="ghost small"
              style={{ flex: "0 0 auto" }}
              onClick={() => cmd(command)}>
              {text}
            </button>
          ),
        )}
        <span className="muted small" style={{ flex: "1 1 auto" }}>
          Pasted text keeps its words, not its styling.
        </span>
      </div>
      <div
        ref={ref}
        className="richtext"
        contentEditable
        role="textbox"
        aria-multiline="true"
        aria-label={label}
        suppressContentEditableWarning
        onInput={emit}
        onBlur={emit}
        onKeyDown={onKeyDown}
        // Enter makes a paragraph, which the clean-up keeps; Chrome's own
        // default (a <div>) is stripped, which merged the lines.
        onFocus={() => document.execCommand("defaultParagraphSeparator", false, "p")}
        onPaste={(e) => {
          // Force plain text: pasting from Word or Gmail is the main source of
          // the `<span style>` soup this editor exists to avoid.
          e.preventDefault();
          const text = e.clipboardData.getData("text/plain");
          document.execCommand("insertText", false, text);
          emit();
        }}
      />
    </div>
  );
}
