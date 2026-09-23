import { Fragment, useEffect } from "react";
import {
  Activity as ActivityIcon, BarChart3, Building2, CalendarCheck, CheckSquare,
  ClipboardList,
  Contact as ContactIcon, FileText, Inbox, LayoutGrid, Mail, PanelLeftClose,
  PanelLeftOpen,
  Reply, Sparkles, Store, Target, Upload, UserCog, Users, Workflow,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { NavLink, Route, Routes, matchPath, useLocation } from "react-router-dom";

import { ActAsColleague, ActingBanner } from "./components/ActAs";
import { Avatar, useRemembered } from "./components/shell";
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
import { Activity } from "./screens/Activity";
import { AiUsage } from "./screens/AiUsage";
import { NoteDetail } from "./screens/NoteDetail";
import { Dashboard } from "./screens/Dashboard";
import { Meetings } from "./screens/Meetings";
import { Replies } from "./screens/Replies";
import { Notes } from "./screens/Notes";
import { PinReset } from "./screens/PinReset";
import { CadenceLink } from "./screens/CadenceLink";
import { PreCallForm } from "./screens/PreCallForm";
import { SessionDetail } from "./screens/SessionDetail";
import { SessionTemplate } from "./screens/SessionTemplate";
import { Sessions } from "./screens/Sessions";
import { Digests } from "./screens/Digests";
import { Report } from "./screens/Report";
import { Tasks } from "./screens/Tasks";
import { Work } from "./screens/Work";
import { WorkParentDetail } from "./screens/WorkParentDetail";

interface Branding {
  display_name: string;
  logo_url: string;
  palette: { header: string; accent: string; gray_dark: string; gray_light: string };
  /** Staff only. A client is never told the product's name. */
  product_name: string | null;
}

const TENANT = ["FF", "CF", "VA"];

/** The five codes are the schema's; nobody signing in thinks of themselves as
 *  an "ECC". */
const ROLE_LABELS: Record<string, string> = {
  FF: "Founder", CF: "Fractional", VA: "Assistant",
  FCC: "Client — founder", ECC: "Client",
};
const CLIENT = ["FCC", "ECC"];

/** `group` is the heading the item sits under in the sidebar. A flat list of
 *  seventeen links is a list nobody reads; the groups say what each part of the
 *  product is for, and they are the same words the modules use. */
type NavItem = {
  to: string; label: string; roles?: string[]; group?: string;
  /** Every nav item has one (design brief, Tier 1). */
  icon: typeof Users;
};

const NAV: NavItem[] = [
  // Matrix 4.18 — Module 1 has no client-facing surface, so every CRM entry is
  // scoped to tenant staff. Without this, an FCC saw the whole sidebar.
  { to: "/dashboard", label: "Dashboard", roles: TENANT, group: "Today", icon: LayoutGrid },
  { to: "/contacts", label: "Contacts", roles: TENANT , group: "Accounts" , icon: ContactIcon },
  { to: "/pipeline", label: "Pipeline", roles: TENANT , icon: Workflow },
  { to: "/companies", label: "Companies", roles: TENANT , icon: Building2 },
  // Matrix 6.9 — notes have no client-visible form in Beta.
  { to: "/notes", label: "Notes", roles: TENANT , icon: FileText },
  // Module 3. The client portal's own navigation arrives with done-item 10.
  { to: "/work", label: "Work", roles: TENANT , group: "The work" , icon: Target },
  { to: "/tasks", label: "Tasks", roles: TENANT , icon: CheckSquare },
  { to: "/digests", label: "Digests", roles: TENANT , icon: Mail },
  // Module 4. A VA sets a session up and sends the form; the call itself is the
  // fractional's, and the screen says so rather than hiding controls (§10).
  { to: "/strategy", label: "Strategy", roles: TENANT , icon: ClipboardList },
  // Module 5 — the queue. No client-facing surface exists (matrix §11).
  { to: "/meetings", label: "Meeting queue", roles: TENANT, icon: CalendarCheck },
  // Module 6 — replies that came back. No client-facing surface either
  // (matrix 12.5): these threads carry correspondence *about* a client.
  { to: "/replies", label: "Replies", roles: TENANT, icon: Reply },
  // Was the client's own log (FR-3.41). The owner reversed that on 2026-09-16:
  // the feed is the practice's view across every account, and a client is
  // refused the endpoint outright.
  { to: "/activity", label: "Activity", roles: TENANT , icon: ActivityIcon },
  // The practice reads the same report the client does, per company.
  { to: "/report", label: "Value report", roles: TENANT , icon: BarChart3 },
  // The client portal: the same work, scoped to their company (FR-3.34).
  { to: "/work", label: "Our work", roles: CLIENT , group: "Your engagement" , icon: Target },
  { to: "/tasks", label: "Tasks", roles: CLIENT , icon: CheckSquare },
  // Module 4B — replaces FR-3.38's progress report. A place they can go,
  // not a document somebody remembered to send.
  { to: "/report", label: "Where we are", roles: CLIENT , icon: BarChart3 },
  { to: "/vendors", label: "Vendors", roles: TENANT , group: "Elsewhere" , icon: Store },
  { to: "/outbox", label: "Outbox", roles: TENANT , icon: Inbox },
  { to: "/import", label: "CSV import", roles: ["FF", "VA"] , icon: Upload },
  { to: "/settings/email", label: "Email settings", roles: ["FF", "CF"] , group: "Settings" , icon: Mail },
  { to: "/referrals", label: "Referral settings", roles: ["FF"] , icon: Users },
  { to: "/rules", label: "Stage automations", roles: ["FF"] , icon: Workflow },
  { to: "/staff", label: "Staff", roles: ["FF"] , icon: UserCog },
  { to: "/ai-usage", label: "AI usage", roles: ["FF"] , icon: Sparkles },
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
  // The two pages reachable with **no session at all**: the cadence link in
  // every digest footer (FR-3.33a) and the pre-call form (FR-4.6, matrix
  // 10.13). They render before the sign-in check below.
  //
  // They are rendered inside <Routes>, not returned bare. `useParams()` reads
  // from the matched route, so a bare element gets an EMPTY params object and
  // the page fetches `/api/.../undefined` — which the server answers, quite
  // correctly, with "this link has expired". That is the 2026-09-19 bug: a
  // valid token, a valid session, and a page that never sent it.
  const isPublic = matchPath("/updates/:token", location.pathname)
    || matchPath("/strategy/precall/:token", location.pathname);
  if (isPublic) {
    return (
      <Routes>
        <Route path="/updates/:token" element={<CadenceLink />} />
        <Route path="/strategy/precall/:token" element={<PreCallForm />} />
      </Routes>
    );
  }

  const { data: me, isLoading, isError } = useQuery<Me>({
    queryKey: ["me"],
    queryFn: () => api.get<Me>("/api/me"),
    retry: false,
  });

  // White-label: every client-facing surface wears the practice's name, colours
  // and logo; only staff screens name the product. Unauthenticated too — the
  // signed-out screen is the first thing a client with a dead session sees.
  const { data: brand } = useQuery<Branding>({
    queryKey: ["branding"],
    queryFn: () => api.get<Branding>("/api/branding"),
    retry: false,
  });
  const staff = !!me?.role && TENANT.includes(me.role);
  // Manual only, and remembered in this browser (design brief, Tier 1).
  const [collapsed, setCollapsed] = useRemembered("enhq.sidebar.collapsed", false);
  const wordmark = (staff ? brand?.product_name : brand?.display_name) ?? "";
  const palette = brand?.palette;

  useEffect(() => {
    if (!palette) return;
    const root = document.documentElement;
    root.style.setProperty("--blue", palette.header);
    root.style.setProperty("--orange", palette.accent);
  }, [palette]);

  useEffect(() => {
    if (wordmark) document.title = wordmark;
  }, [wordmark]);

  if (isLoading) return <main style={{ padding: "2rem" }}>Loading…</main>;

  if (isError || !me?.authenticated) {
    return (
      <main style={{ padding: "3rem", textAlign: "center" }}>
        <h2>{brand?.display_name || "Sign in"}</h2>
        <p className="muted">You are not signed in.</p>
        <a className="btn" href="/accounts/google/login/">Sign in with Google</a>
      </main>
    );
  }

  const visible = NAV.filter((n) => !n.roles || (me.role && n.roles.includes(me.role)));

  return (
    <div className={collapsed ? "layout collapsed" : "layout"}>
      <aside className="sidebar">
        <div className="brand">
          {brand?.logo_url && !staff
            ? <img src={brand.logo_url} alt={wordmark} />
            : <h1>{wordmark}</h1>}
        </div>
        {me.role && TENANT.includes(me.role) && <NoteCapture defaults={captureDefaults(location.pathname)} />}
        <nav>
          {visible.map((n) => (
            <Fragment key={`${n.to}-${n.label}`}>
              {n.group && <div className="nav-group">{n.group}</div>}
              <NavLink to={n.to} end={n.to === "/work" || n.to === "/report"}
                title={collapsed ? n.label : undefined}
                className={({ isActive }) => (isActive ? "active" : "")}>
                <n.icon size={18} strokeWidth={1.75} aria-hidden="true" />
                <span className="label">{n.label}</span>
              </NavLink>
            </Fragment>
          ))}
        </nav>
        <button className="collapse" aria-label={collapsed ? "Expand the menu" : "Collapse the menu"}
          onClick={() => setCollapsed(!collapsed)}>
          {collapsed ? <PanelLeftOpen size={18} strokeWidth={1.75} />
            : <><PanelLeftClose size={18} strokeWidth={1.75} /> <span>Collapse</span></>}
        </button>
        <div className="who">
          <Avatar name={me.full_name || me.email} size="lg" />
          <div className="names" style={{ minWidth: 0 }}>
            <div className="name">{me.full_name || me.email}</div>
            <div className="role">{ROLE_LABELS[me.role!] ?? me.role}</div>
            <ActAsColleague me={me} />
          </div>
        </div>
      </aside>
      <main>
        {/* FR-3.42 — never dismissible; stopping is the only way out. */}
        <ActingBanner me={me} />
        <ErrorBoundary>
          {me.role && TENANT.includes(me.role) && <PendingUploads />}
          <Routes>
            {/* The landing page (design brief, Tier 2). A client user never
                reaches it: their landing page is the portal. */}
            <Route path="/" element={
              me.role && TENANT.includes(me.role)
                ? <Dashboard me={me} /> : <Contacts me={me} />} />
            <Route path="/dashboard" element={<Dashboard me={me} />} />
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
            <Route path="/tasks" element={<Tasks me={me} />} />
            {/* The editor is a panel over the board, not a page of its own
                (design brief, Tier 1), so the task's URL renders the board
                with the sheet on top of it. */}
            <Route path="/tasks/:id" element={<Tasks me={me} />} />
            <Route path="/work" element={<Work me={me} />} />
            <Route path="/work/goals/:id" element={<WorkParentDetail me={me} kind="goal" />} />
            <Route path="/work/projects/:id" element={<WorkParentDetail me={me} kind="project" />} />
            <Route path="/meetings" element={<Meetings me={me} />} />
            <Route path="/replies" element={<Replies me={me} />} />
            <Route path="/strategy" element={<Sessions me={me} />} />
            <Route path="/strategy/template" element={<SessionTemplate me={me} />} />
            <Route path="/strategy/:id" element={<SessionDetail me={me} />} />
            <Route path="/digests" element={<Digests me={me} />} />
            <Route path="/report" element={<Report me={me} />} />
            <Route path="/report/:id" element={<Report me={me} />} />
            <Route path="/activity" element={<Activity me={me} />} />
          </Routes>
        </ErrorBoundary>
      </main>
    </div>
  );
}
