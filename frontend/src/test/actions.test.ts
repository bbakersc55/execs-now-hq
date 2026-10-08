/**
 * Actions are buttons; links go somewhere (2026-10-08).
 *
 * "View portal as…", "Resend invitation", "Revoke" and "Set as primary contact"
 * were drawn as links: borderless, and a button only under the mouse. An action
 * that reads as a link is an action people do not see, and one that is an
 * anchor lies to the keyboard and to a screen reader about what it does.
 *
 * Two halves, both read from the source rather than from one rendered screen,
 * so a new screen is covered the day it is written:
 *
 * 1. No anchor carries an action. Every `<a>`, `<Link>` and `<NavLink>` has a
 *    real destination, and none has a click handler that does anything but
 *    get out of the way of the navigation it is already doing.
 * 2. Every button style has the button look at rest.
 */
// @ts-expect-error — the app has no Node types; the test runner is Node.
import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const sources = import.meta.glob(["../**/*.tsx", "!../**/*.test.tsx"], {
  query: "?raw", import: "default", eager: true,
}) as Record<string, string>;

/** Every opening tag of the given names, whole: JSX attributes hold `>` inside
 *  `=>` and `{...}`, so the end of a tag is the first `>` outside any braces. */
function openingTags(source: string, names: string[]) {
  const found: { tag: string; line: number }[] = [];
  const start = new RegExp(`<(${names.join("|")})(?=[\\s>])`, "g");
  for (let m = start.exec(source); m; m = start.exec(source)) {
    let depth = 0;
    let end = m.index;
    for (; end < source.length; end += 1) {
      const ch = source[end];
      if (ch === "{") depth += 1;
      else if (ch === "}") depth -= 1;
      else if (ch === ">" && depth === 0) break;
    }
    found.push({ tag: source.slice(m.index, end + 1),
                 line: source.slice(0, m.index).split("\n").length });
  }
  return found;
}

/** The body of `name={...}` in a tag, or null. */
function attribute(tag: string, name: string) {
  const at = tag.search(new RegExp(`\\s${name}=`));
  if (at < 0) return null;
  const from = tag.indexOf("=", at) + 1;
  if (tag[from] === '"') return tag.slice(from + 1, tag.indexOf('"', from + 1));
  let depth = 0;
  for (let i = from; i < tag.length; i += 1) {
    if (tag[i] === "{") depth += 1;
    if (tag[i] === "}") { depth -= 1; if (depth === 0) return tag.slice(from + 1, i); }
  }
  return tag.slice(from);
}

/** What a click on a link may do besides follow it: keep the click from also
 *  toggling the row it sits in, or close the menu it was chosen from. Nothing
 *  that changes a record. */
const HARMLESS = [
  /^\(e\) => e\.stopPropagation\(\)$/,
  /^\(\) => setOpen\(false\)$/,
];

describe("no action is rendered as an anchor", () => {
  const anchors = Object.entries(sources).flatMap(([file, source]) =>
    openingTags(source, ["a", "Link", "NavLink"]).map((found) => ({ file, ...found })));

  it("finds the anchors it is meant to be checking", () => {
    expect(anchors.length).toBeGreaterThan(40);
    // The scanner reads a tag with an arrow function in it to its real end.
    const tricky = openingTags(
      '<Link className="rowname" to={`/work/goals/${goal.id}`}\n  onClick={(e) => e.stopPropagation()}>x</Link>',
      ["Link"]);
    expect(tricky).toHaveLength(1);
    expect(attribute(tricky[0].tag, "onClick")).toBe("(e) => e.stopPropagation()");
    expect(attribute(tricky[0].tag, "to")).toBe("`/work/goals/${goal.id}`");
  });

  it("every anchor goes somewhere", () => {
    const nowhere = anchors.filter(({ tag }) => {
      const to = attribute(tag, "to") ?? attribute(tag, "href");
      // `{...rowLink(...)}`-style spreads carry their own destination.
      if (to === null) return !/\{\.\.\./.test(tag);
      return ["", "#", "javascript:void(0)"].includes(to.trim());
    });
    expect(nowhere.map((a) => `${a.file}:${a.line} ${a.tag.slice(0, 80)}`)).toEqual([]);
  });

  it("no anchor has a click handler that does something", () => {
    const acting = anchors.filter(({ tag }) => {
      const handler = attribute(tag, "onClick");
      return handler !== null && !HARMLESS.some((ok) => ok.test(handler.trim()));
    });
    expect(acting.map((a) => `${a.file}:${a.line} ${a.tag.slice(0, 100)}`)).toEqual([]);
  });

  it("no anchor is dressed as a button with a role", () => {
    const dressed = anchors.filter(({ tag }) => /role="button"/.test(tag));
    expect(dressed.map((a) => `${a.file}:${a.line}`)).toEqual([]);
  });

  it("the row and panel actions named in the brief are buttons", () => {
    const where: Record<string, string> = {
      "View portal as…": "../components/ActAs.tsx",
      "Resend invitation": "../components/PortalAccessCard.tsx",
      "Revoke": "../components/PortalAccessCard.tsx",
      "Set as primary contact": "../screens/CompanyDetail.tsx",
    };
    for (const [label, file] of Object.entries(where)) {
      const source = sources[file];
      const buttons = openingTags(source, ["button"]);
      const holding = buttons.find(({ tag }) => {
        const after = source.slice(source.indexOf(tag) + tag.length, source.indexOf(tag) + tag.length + 120);
        return after.trimStart().startsWith(label);
      });
      expect(holding, `${label} is not the text of a <button> in ${file}`).toBeTruthy();
    }
  });
});

describe("every button looks like a button at rest", () => {
  const css: string = readFileSync("src/theme.css", "utf8");
  const rule = (selector: string) => {
    const at = css.indexOf(`\n${selector} {`);
    expect(at, `no rule for ${selector}`).toBeGreaterThan(-1);
    return css.slice(at, css.indexOf("}", at));
  };

  it("the plain button, which is the secondary one, has a border and a fill", () => {
    expect(rule("button, .btn")).toMatch(/border: 1px solid var\(--line-strong\)/);
    expect(rule("button, .btn")).toMatch(/background: var\(--surface\)/);
  });

  it("the tertiary button has a fill at rest, not a transparent one", () => {
    expect(rule("button.ghost, .btn.ghost")).toMatch(/background: color-mix/);
    expect(rule("button.ghost, .btn.ghost")).not.toMatch(/background: transparent/);
  });

  it("a small action on a row or a panel is bordered", () => {
    const small = rule("button.ghost.small, .btn.ghost.small");
    expect(small).toMatch(/border-color: var\(--line-strong\)/);
    expect(small).toMatch(/background: var\(--surface\)/);
  });

  it("an action inside a sentence is a button too: filled, and not underlined", () => {
    expect(rule("button.link")).toMatch(/background: color-mix/);
    expect(rule("button.link")).toMatch(/text-decoration: none/);
    expect(rule("button.link")).not.toMatch(/underline/);
  });

  it("row actions are there at rest, not only under the mouse", () => {
    expect(css).not.toMatch(/\.rowactions button \{[^}]*opacity: 0/);
  });
});

describe("the page uses the window, and what is read does not stretch", () => {
  const css: string = readFileSync("src/theme.css", "utf8");
  const rule = (selector: string) => {
    const at = css.indexOf(`\n${selector} {`);
    expect(at, `no rule for ${selector}`).toBeGreaterThan(-1);
    return css.slice(at, css.indexOf("}", at));
  };

  it("the page goes to 1600px", () => {
    expect(rule("main")).toMatch(/max-width: 1600px/);
  });

  it("the Tasks board takes the full width and its columns share it before it scrolls", () => {
    expect(rule("main:has(.board)")).toMatch(/max-width: none/);
    expect(rule(".board .col")).toMatch(/flex: 1 1 232px; min-width: 232px/);
    expect(rule(".board")).toMatch(/overflow: auto/);
  });

  it("a form, a record and anything typed into stop at 720px", () => {
    expect(css).toMatch(
      /\.record, main \.card:has\(> form\), \.settings-body > \.card:not\(:has\(table\)\) \{ max-width: 720px; \}/);
    expect(css).toMatch(/main :is\(textarea, select, input[^{]*\{\s*max-width: 720px;/);
    expect(rule(".record-cols")).toMatch(/minmax\(0, 720px\) minmax\(0, 560px\)/);
  });

  it("a list of cards takes as many columns as fit, and the open card the whole row", () => {
    expect(rule(".card-grid")).toMatch(/repeat\(auto-fill, minmax\(min\(100%, 440px\), 1fr\)\)/);
    expect(rule(".card-grid > .open")).toMatch(/grid-column: 1 \/ -1/);
  });

  it("wide windows get larger type and padding in those cards, not wider boxes", () => {
    const wide = css.slice(css.indexOf("@media (min-width: 1400px)"));
    expect(wide.slice(0, 400)).toMatch(/\.card-grid \.card \{ padding: var\(--s6\); \}/);
    expect(wide.slice(0, 400)).toMatch(/font-size/);
  });

  it("the acting-as bar is one wrapping line across the content area", () => {
    const bar = rule(".acting-bar .banner");
    expect(bar).toMatch(/flex-wrap: wrap/);
    expect(bar).toMatch(/border-radius: 0/);
    expect(rule(".acting-bar .banner button")).toMatch(/white-space: nowrap/);
  });
});
