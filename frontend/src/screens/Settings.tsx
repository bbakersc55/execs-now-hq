import { ReactNode } from "react";
import { NavLink, Navigate, useLocation } from "react-router-dom";

import { ErrorBoundary } from "../components/ErrorBoundary";
import { PageHead } from "../components/shell";
import { Empty } from "../components/ui";
import { Me } from "../lib/api";

type Role = NonNullable<Me["role"]>;

/**
 * The sections of Settings and who sees each (UI 3 spec §4).
 *
 * These are the roles the sidebar's Settings group listed each screen for, so
 * the move shows nobody a section they were not already shown. It decides
 * what is *listed*; what a person may read or change is still each screen's
 * own endpoint, as before. The addresses are the ones the screens always had
 * (D4), so links in the app and in emails keep working.
 */
export const SETTINGS: { to: string; label: string; roles: Role[] }[] = [
  { to: "/settings/email", label: "Email", roles: ["FF", "CF"] },
  { to: "/settings/branding", label: "Branding", roles: ["FF"] },
  // "Team", not "Staff", which a new owner read as his client's staff (beta
  // feedback, 2026-10-05). The address stays /staff so links keep working.
  { to: "/staff", label: "Team", roles: ["FF"] },
  { to: "/rules", label: "Stage automations", roles: ["FF"] },
  { to: "/referrals", label: "Referral settings", roles: ["FF"] },
  { to: "/settings/digests", label: "Digests", roles: ["FF"] },
  { to: "/settings/notes", label: "Notes", roles: ["FF"] },
  { to: "/ai-usage", label: "AI usage", roles: ["FF"] },
];

export function settingsFor(me: Me) {
  // The Practices area binds no practice, so it has no practice settings.
  if (me.area === "platform" || !me.role) return [];
  return SETTINGS.filter((section) => section.roles.includes(me.role as Role));
}

/**
 * One page: the sections this person has on the left, the chosen one beside
 * them. With no `children` it is `/settings` itself, which opens the first.
 *
 * Someone with no sections who follows a link to a settings screen gets that
 * screen exactly as before, with nothing listed beside it: listing is not
 * access, in either direction.
 */
export function Settings({ me, children }: { me: Me; children?: ReactNode }) {
  const sections = settingsFor(me);
  const { pathname } = useLocation();
  if (!children) {
    if (sections.length > 0) return <Navigate to={sections[0].to} replace />;
    return (
      <>
        <PageHead title="Settings" />
        <Empty>There are no settings for your role.</Empty>
      </>
    );
  }
  if (sections.length === 0) return <>{children}</>;

  return (
    <div className="settings">
      <nav className="settings-nav" aria-label="Settings">
        <div className="heading">Settings</div>
        {sections.map((section) => (
          <NavLink key={section.to} to={section.to}
            className={({ isActive }) => (isActive ? "on" : "")}>
            {section.label}
          </NavLink>
        ))}
      </nav>
      {/* Its own boundary, keyed by section: a section that fails leaves the
          list standing, and choosing another one clears the failure. */}
      <div className="settings-body">
        <ErrorBoundary key={pathname}>{children}</ErrorBoundary>
      </div>
    </div>
  );
}
