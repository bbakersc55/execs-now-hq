/**
 * The client portal wears its practice's colors (P1, owner 2026-10-02).
 *
 * The stylesheet is written against the product's token family (--navy,
 * --navy-700, --navy-300, --orange, --orange-600, --orange-050) and reads
 * `var(--navy)` everywhere; until P1 the portal only set --blue/--orange,
 * which nothing reads, so a practice's colors never arrived. This derives the
 * whole family from the practice's two colors, the way the product's own
 * shades relate to its navy and orange.
 *
 * Staff screens never get these: they keep the product's look.
 */
import { textOn } from "./contrast";

function parse(hex: string): [number, number, number] {
  return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)) as [number, number, number];
}

function toHex([r, g, b]: number[]): string {
  return "#" + [r, g, b].map((v) => Math.round(v).toString(16).padStart(2, "0")).join("");
}

/** `amount` of the way from `hex` to `toward` (0 = hex, 1 = toward). */
export function mix(hex: string, toward: string, amount: number): string {
  const a = parse(hex);
  const b = parse(toward);
  return toHex(a.map((v, i) => v + (b[i] - v) * amount));
}

export const PORTAL_TOKENS = [
  "--navy", "--navy-700", "--navy-300", "--orange", "--orange-600", "--orange-050",
  "--on-orange", "--focus",
] as const;

export function portalTokens(primary: string, accent: string): Record<string, string> {
  const [r, g, b] = parse(primary);
  return {
    "--navy": primary,
    "--navy-700": mix(primary, "#ffffff", 0.08),
    "--navy-300": mix(primary, "#ffffff", 0.45),
    "--orange": accent,
    "--orange-600": mix(accent, "#000000", 0.1),
    "--orange-050": mix(accent, "#ffffff", 0.93),
    // Text on an accent fill: white or near-black, whichever reads (D4).
    "--on-orange": textOn(accent),
    "--focus": `0 0 0 3px rgba(${r}, ${g}, ${b}, .20)`,
  };
}

/** Set the practice's tokens (client users), or remove them (staff). */
export function applyPortalTokens(root: HTMLElement,
  colors: { primary: string; accent: string } | null) {
  if (colors === null) {
    PORTAL_TOKENS.forEach((name) => root.style.removeProperty(name));
    return;
  }
  for (const [name, value] of Object.entries(portalTokens(colors.primary, colors.accent))) {
    root.style.setProperty(name, value);
  }
}
