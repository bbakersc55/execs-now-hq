import { Banner } from "../components/ui";
import { Me } from "../lib/api";
import { YourSubscription } from "./YourSubscription";

/**
 * P4 part 5 (D2): a suspended practice. Its staff see only this. The
 * practice owner pays here, and paying lifts it at once; nothing in the
 * practice was changed.
 */
export function Suspended({ me }: { me: Me }) {
  return (
    <main style={{ padding: "2rem 1rem", maxWidth: "44rem", margin: "0 auto" }}>
      <h1>Your practice is suspended until the invoice is paid</h1>
      <Banner kind="warn">
        An Execs NOW HQ invoice has been unpaid for 30 days. Nothing in your practice has been
        changed or removed; it is all here as soon as the invoice is paid.
      </Banner>
      {me.role === "FF" ? <YourSubscription />
        : <p>Your practice owner can pay it under Settings → Billing.</p>}
      <p className="small"><a href="/auth/sign-out">Sign out</a></p>
    </main>
  );
}
