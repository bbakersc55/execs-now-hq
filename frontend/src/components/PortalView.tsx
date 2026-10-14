import { Me } from "../lib/api";
import { useRemembered } from "../lib/remembered";

/**
 * P7 §4.3 — "Mine / My team / Everyone", for a manager, a senior leader and
 * the client owner. The server narrows the lists (`?view=`) and never widens
 * them; "Everyone" is what the person sees today, which is where it starts.
 */
export type PortalViewName = "mine" | "team" | "everyone";

const LABEL: Record<PortalViewName, string> = {
  mine: "Mine", team: "My team", everyone: "Everyone",
};

export function usePortalView(me: Me) {
  const offered = !!me.portal?.has_teams_view;
  const [chosen, choose] = useRemembered<PortalViewName>(
    `portal-view-${me.email}`, "everyone");
  const view: PortalViewName = offered ? chosen : "everyone";
  return {
    offered, view, choose,
    /** For a list's URL: "" when nothing narrows it. */
    param: view === "everyone" ? "" : `view=${view}`,
  };
}

export function PortalViewSwitch({ value, onChange }: {
  value: PortalViewName; onChange: (view: PortalViewName) => void;
}) {
  return (
    <div className="row" role="group" aria-label="Whose work">
      {(Object.keys(LABEL) as PortalViewName[]).map((view) => (
        <button key={view} type="button" aria-pressed={value === view}
          className={value === view ? "small primary" : "small"}
          onClick={() => onChange(view)}>{LABEL[view]}</button>
      ))}
    </div>
  );
}
