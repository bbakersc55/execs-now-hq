/**
 * The contrast rules for a practice's two colors (P1, D4), for the Branding
 * screen's live preview. A mirror of apps/tenancy/contrast.py, which is what
 * actually accepts or refuses a save; both are tested against
 * contrast-reference.json.
 */
export const WHITE = "#FFFFFF";
export const NEAR_BLACK = "#1F2933";
export const HEX = /^#[0-9A-Fa-f]{6}$/;

function channel(value: number): number {
  const c = value / 255;
  return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
}

export function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16));
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function ratio(a: string, b: string): number {
  const [high, low] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (high + 0.05) / (low + 0.05);
}

/** White or near-black, whichever reads better on `fill`. */
export function textOn(fill: string): string {
  return ratio(fill, WHITE) >= ratio(fill, NEAR_BLACK) ? WHITE : NEAR_BLACK;
}

export interface Check {
  rule: "primary_on_white" | "accent_on_primary" | "accent_on_white";
  label: string;
  ratio: number;
  required: number;
  blocks: boolean;
  ok: boolean;
}

export function check(primary: string, accent: string): Check[] {
  const rows: Omit<Check, "ok">[] = [
    { rule: "primary_on_white", label: "Primary color against white",
      ratio: ratio(primary, WHITE), required: 4.5, blocks: true },
    { rule: "accent_on_primary", label: "Accent against the primary color",
      ratio: ratio(accent, primary), required: 3, blocks: true },
    { rule: "accent_on_white", label: "Accent against white (used as decoration only)",
      ratio: ratio(accent, WHITE), required: 3, blocks: false },
  ];
  return rows.map((r) => ({ ...r, ok: r.ratio >= r.required }));
}
