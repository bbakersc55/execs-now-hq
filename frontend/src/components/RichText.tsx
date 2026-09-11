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

export function RichText({ value, onChange, label }: {
  value: string;
  onChange: (html: string, text: string) => void;
  label: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // Only write into the DOM when the editor is not the source of the change,
    // or the caret jumps to the start on every keystroke.
    if (ref.current && ref.current.innerHTML !== value) {
      ref.current.innerHTML = value;
    }
  }, [value]);

  function emit() {
    const html = sanitize(ref.current?.innerHTML ?? "");
    onChange(html, toPlainText(html));
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
