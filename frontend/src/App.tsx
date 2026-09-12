import { useQuery } from "@tanstack/react-query";
import { NavLink, Route, Routes, matchPath, useLocation } from "react-router-dom";

import { ErrorBoundary } from "./components/ErrorBoundary";
import { NoteCapture } from "./components/NoteCapture";
import { PendingUploads } from "./components/PendingUploads";
import { api, Me } from "./lib/api";
import { ContactDetail } from "./screens/ContactDetail";
import { EmailSettings } from "./screens/EmailSettings";
import { Contacts } from "./screens/Contacts";
import { CompanyDetail } from "./screens/CompanyDetail";
import { Companies } from "./screens/Companies";
import { ImportWizard } from "./screens/ImportWizard";
import { Merge } from "./screens/Merge";
import { Outbox } from "./screens/Outbox";
import { Pipeline } from "./screens/Pipeline";
import { ReferralSettings } from "./screens/ReferralSettings";
import { StageRules } from "./screens/StageRules";
import { Staff } from "./screens/Staff";
import { Vendors } from "./screens/Vendors";
import { AiUsage } from "./screens/AiUsage";
import { NoteDetail } from "./screens/NoteDetail";
import { Notes } from "./screens/Notes";
import { PinReset } from "./screens/PinReset";
import { TaskDetail } from "./screens/TaskDetail";
import { Work } from "./screens/Work";
import { WorkParentDetail } from "./screens/WorkParentDetail";

const TENANT = ["FF", "CF", "VA"];

const NAV: { to: string; label: string; roles?: string[] }[] = [
  // Matrix 4.18 — Module 1 has no client-facing surface, so every CRM entry is
  // scoped to tenant staff. Without this, an FCC saw the whole sidebar.
  { to: "/contacts", label: "Contacts", roles: TENANT },
  { to: "/pipeline", label: "Pipeline", roles: TENANT },
  { to: "/companies", label: "Companies", roles: TENANT },
  // Matrix 6.9 — notes have no client-visible form in Beta.
  { to: "/notes", label: "Notes", roles: TENANT },
  // Module 3. The client portal's own navigation arrives with done-item 10.
  { to: "/work", label: "Work", roles: TENANT },
  { to: "/vendors", label: "Vendors", roles: TENANT },
  { to: "/outbox", label: "Outbox", roles: TENANT },
  { to: "/import", label: "CSV import", roles: ["FF", "VA"] },
  { to: "/settings/email", label: "Email settings", roles: ["FF", "CF"] },
  { to: "/referrals", label: "Referral settings", roles: ["FF"] },
  { to: "/rules", label: "Stage automations", roles: ["FF"] },
  { to: "/staff", label: "Staff", roles: ["FF"] },
  { to: "/ai-usage", label: "AI usage", roles: ["FF"] },
];

/** Pre-link a new note to the record on screen; everything else stays optional. */
function captureDefaults(pathname: string) {
  const contact = matchPath("/contacts/:id", pathname);
  if (contact) return { contact: contact.params.id ?? null };
  const company = matchPath("/companies/:id", pathname);
  if (company) return { company: company.params.id ?? null };
  const task = matchPath("/tasks/:id", pathname);
  if (task) return { task: task.params.id ?? null };
  return {};
}

export function App() {
  const location = useLocation();
  const { data: me, isLoading, isError } = useQuery<Me>({
    queryKey: ["me"],
    queryFn: () => api.get<Me>("/api/me"),
    retry: false,
  });

  if (isLoading) return <main style={{ padding: "2rem" }}>Loading…</main>;

  if (isError || !me?.authenticated) {
    return (
      <main style={{ padding: "3rem", textAlign: "center" }}>
        <h2>Execs NOW HQ</h2>
        <p className="muted">You are not signed in.</p>
        <a className="btn" href="/accounts/google/login/">Sign in with Google</a>
      </main>
    );
  }

  const visible = NAV.filter((n) => !n.roles || (me.role && n.roles.includes(me.role)));

  return (
    <div className="layout">
      <aside className="sidebar">
        <h1>Execs NOW HQ</h1>
        {me.role && TENANT.includes(me.role) && <NoteCapture defaults={captureDefaults(location.pathname)} />}
        <nav>
          {visible.map((n) => (
            <NavLink key={n.to} to={n.to} className={({ isActive }) => (isActive ? "active" : "")}>
              {n.label}
            </NavLink>
          ))}
        </nav>
        <div className="who">
          {me.full_name || me.email}
          <br />
          <span className="pill" style={{ marginTop: ".4rem" }}>{me.role}</span>
        </div>
      </aside>
      <main>
        <ErrorBoundary>
          {me.role && TENANT.includes(me.role) && <PendingUploads />}
          <Routes>
            <Route path="/" element={<Contacts me={me} />} />
            <Route path="/contacts" element={<Contacts me={me} />} />
            <Route path="/contacts/:id" element={<ContactDetail me={me} />} />
            <Route path="/merge/:aId/:bId" element={<Merge />} />
            <Route path="/pipeline" element={<Pipeline />} />
            <Route path="/companies" element={<Companies me={me} />} />
            <Route path="/companies/:id" element={<CompanyDetail me={me} />} />
            <Route path="/vendors" element={<Vendors />} />
            <Route path="/outbox" element={<Outbox />} />
            <Route path="/import" element={<ImportWizard />} />
            <Route path="/settings/email" element={<EmailSettings me={me} />} />
            <Route path="/referrals" element={<ReferralSettings />} />
            <Route path="/rules" element={<StageRules />} />
            <Route path="/staff" element={<Staff />} />
            <Route path="/ai-usage" element={<AiUsage />} />
            <Route path="/notes" element={<Notes me={me} />} />
            <Route path="/notes/pin-reset/:token" element={<PinReset />} />
            <Route path="/notes/:id" element={<NoteDetail me={me} />} />
            <Route path="/tasks/:id" element={<TaskDetail me={me} />} />
            <Route path="/work" element={<Work me={me} />} />
            <Route path="/work/goals/:id" element={<WorkParentDetail me={me} kind="goal" />} />
            <Route path="/work/projects/:id" element={<WorkParentDetail me={me} kind="project" />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
