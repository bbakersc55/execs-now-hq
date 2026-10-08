/**
 * Money is whole cents everywhere in the app (P4A). These are the only two
 * places it meets text, and neither goes through a floating-point number of
 * dollars: 19.99 * 100 is not 1999.
 */

/** `$1,234.56`, from cents. */
export function dollars(cents: number): string {
  const sign = cents < 0 ? "-" : "";
  const whole = Math.floor(Math.abs(cents) / 100);
  const part = String(Math.abs(cents) % 100).padStart(2, "0");
  return `${sign}$${whole.toLocaleString("en-US")}.${part}`;
}

/** Cents from what someone typed ("1,200", "$45.5", "19.99"), or null when it
 *  is not an amount. */
export function toCents(text: string): number | null {
  const clean = text.replace(/[$,\s]/g, "");
  const match = /^(\d+)(?:\.(\d{0,2}))?$/.exec(clean);
  if (!match) return null;
  return Number(match[1]) * 100 + Number((match[2] ?? "").padEnd(2, "0"));
}

/** What to show in a box for an amount in cents: "1200.50". */
export function plain(cents: number): string {
  return `${Math.floor(cents / 100)}.${String(cents % 100).padStart(2, "0")}`;
}

/** Quantity (to two decimals) times a price in cents, rounded once, half up:
 *  the same sum the server does. */
export function lineAmount(quantity: string, unitPriceCents: number): number {
  const hundredths = toCents(quantity);
  if (hundredths === null) return 0;
  return Math.floor((hundredths * unitPriceCents + 50) / 100);
}

/** "October 16, 2026" from "2026-10-16", with no time zone to shift the day. */
export function longDate(iso: string): string {
  const [year, month, day] = iso.split("-").map(Number);
  return new Date(Date.UTC(year, month - 1, day)).toLocaleDateString("en-US", {
    month: "long", day: "numeric", year: "numeric", timeZone: "UTC" });
}
