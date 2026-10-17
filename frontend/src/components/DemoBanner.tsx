import { DemoVisitorBanner } from "./DemoVisitor";
import { Banner } from "./ui";
import { Me } from "../lib/api";

const STAFF = ["FF", "CF", "VA"];

/** The demo, said plainly to staff (owner, 2026-09-29): a fictional practice
 *  where nothing real is read, and (2026-10-08) nothing sent reaches the
 *  person it is addressed to. */
export function DemoBanner({ me }: { me: Me }) {
  if (me.environment !== "demo" || !me.role || !STAFF.includes(me.role)) return null;
  // A visitor's own copy says what it is, its way (2026-10-17).
  if (me.demo_visitor) return <DemoVisitorBanner me={me} />;
  return (
    <Banner kind="warn">
      <strong>Demo</strong> — a fictional practice. Nobody in it receives email:
      anything sent goes only to the demo's own inbox. No real mailbox or Drive is
      read. It is reset from time to time.
    </Banner>
  );
}
