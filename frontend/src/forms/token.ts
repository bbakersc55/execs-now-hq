/** The token is the last part of the address: /<token> on the form's own
 *  domain, /forms/<slug>/<token> otherwise. An owner agreement's page is the
 *  same with /a/ before the token. */
export function tokenFrom(path: string): string | null {
  const last = path.replace(/\/+$/, "").split("/").pop() ?? "";
  return /^[A-Za-z0-9_-]{20,100}$/.test(last) ? last : null;
}

/** Whether the page is an owner agreement's (…/a/<token>). */
export function isAgreement(path: string): boolean {
  return /\/a\/[A-Za-z0-9_-]{20,100}\/?$/.test(path);
}
