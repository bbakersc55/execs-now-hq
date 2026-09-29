import { Banner } from "./ui";
import { Me } from "../lib/api";

const STAFF = ["FF", "CF", "VA"];

/** The demo, said plainly to staff (owner, 2026-09-29): a fictional practice
 *  where nothing sends and nothing real is read. */
export function DemoBanner({ me }: { me: Me }) {
  if (me.environment !== "demo" || !me.role || !STAFF.includes(me.role)) return null;
  return (
    <Banner kind="warn">
      <strong>Demo</strong> — a fictional practice. No email is sent and no real
      mailbox or Drive is read. It is reset from time to time.
    </Banner>
  );
}
