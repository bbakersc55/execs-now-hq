/** The token is the last part of the address: /<token> on the form's own
 *  domain, /forms/<slug>/<token> otherwise. */
export function tokenFrom(path: string): string | null {
  const last = path.replace(/\/+$/, "").split("/").pop() ?? "";
  return /^[A-Za-z0-9_-]{20,100}$/.test(last) ? last : null;
}
