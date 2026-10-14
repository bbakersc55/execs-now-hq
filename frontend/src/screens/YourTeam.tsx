import { ClientTeamsCard } from "../components/ClientTeams";
import { PageHead } from "../components/shell";
import { Me } from "../lib/api";

/**
 * P7 phase 3 — the client owner's own Teams card (§4.2), in the portal.
 *
 * The same card the practice has on the company's page: make, rename and
 * archive teams, put people on them at a level, and set what each may create.
 * It does not invite people or change seats; that stays with the practice.
 * The client owner's alone: the route is drawn for no one else.
 */
export function YourTeam({ me }: { me: Me }) {
  if (!me.client_company) return null;
  return (
    <>
      <PageHead title="Your team"
        sub="Who sees and changes which work in the portal, team by team." />
      <ClientTeamsCard me={me} company={{ id: me.client_company, is_client_company: true }} />
    </>
  );
}
