/**
 * What each role is called wherever a person reads it (P1, owner 2026-10-02).
 * The codes are the schema's and never shown. The backend twin is
 * apps/tenancy/roles.py; tests/test_vocabulary.py keeps the two identical.
 */
export const ROLE_LABEL: Record<string, string> = {
  FF: "Practice owner",
  CF: "Associate",
  VA: "Assistant",
  FCC: "Client owner",
  ECC: "Client team member",
};

/** Shown for a code this list does not know: never the code itself. */
export const UNKNOWN_ROLE = "Team member";

export function roleLabel(code: string | null | undefined): string {
  return (code && ROLE_LABEL[code]) || UNKNOWN_ROLE;
}

/** The roles a practice can invite, in the order the pickers list them. */
export const STAFF_ROLES = ["FF", "CF", "VA"] as const;
/** The two portal roles a client user can hold. */
export const PORTAL_ROLE_CODES = ["FCC", "ECC"] as const;
