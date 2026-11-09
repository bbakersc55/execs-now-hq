import { ReactNode } from "react";
import { Navigate } from "react-router-dom";
import { PORTAL_ROLE_CODES, STAFF_ROLES } from "../lib/roles";

/** A client user's landing page: the portal's Our work. */
export const CLIENT_LANDING = "/work";

/**
 * What "/" shows, by role. Every sign-in (a magic link, Google) ends on "/",
 * so a client user must never be handed a staff screen there: before this, a
 * client opening a sign-in link landed on the practice's Contacts, and the
 * API refused every request it made (found 2026-11-09).
 */
export function Landing({ role, staff, other }: {
  role: string | null | undefined; staff: ReactNode; other: ReactNode;
}) {
  if (role && (PORTAL_ROLE_CODES as readonly string[]).includes(role))
    return <Navigate to={CLIENT_LANDING} replace />;
  if (role && (STAFF_ROLES as readonly string[]).includes(role)) return <>{staff}</>;
  return <>{other}</>;
}
