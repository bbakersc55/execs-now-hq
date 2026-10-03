import { Fragment, useEffect } from "react";
import {
  Activity as ActivityIcon, BarChart3, Building2, CalendarCheck, CheckSquare,
  ClipboardList, Palette,
  Contact as ContactIcon, FileText, Inbox, LayoutGrid, Mail, PanelLeftClose,
  PanelLeftOpen,
  Reply, Sparkles, Store, Target, Upload, UserCog, Users, Workflow, Megaphone, Send, Hourglass,
} from "lucide-react";
import { useQuery } from "@tanstack/react-query";
import { NavLink, Route, Routes, matchPath, useLocation } from "react-router-dom";

import { ActAsColleague, ActingBanner } from "./components/ActAs";
import { Avatar, useNarrowWindow, useRemembered } from "./components/shell";
import { ToastHost } from "./components/ui";
import { DemoBanner } from "./components/DemoBanner";
import { SignedOut } from "./components/SignedOut";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { NoteCapture } from "./components/NoteCapture";
import { PendingUploads } from "./components/PendingUploads";
import { api, Me } from "./lib/api";
import { PRODUCT_FAVICON, setFavicon, useBranding } from "./lib/branding";
import { applyPortalTokens } from "./lib/palette";
import { LinkBranded } from "./components/LinkBranded";
import { AreaSwitch } from "./components/AreaSwitch";
import { AgreementGate } from "./components/AgreementGate";
import { FeedbackButton } from "./components/FeedbackButton";
import { roleLabel } from "./lib/roles";
import { ContactDetail } from "./screens/ContactDetail";
import { EmailSettings } from "./screens/EmailSettings";
import { Contacts } from "./screens/Contacts";
import { CompanyDetail } from "./screens/CompanyDetail";
import { Companies } from "./screens/Companies";
import { ImportWizard } from "./screens/ImportWizard";
import { Merge } from "./screens/Merge";
import { Duplicates } from "./screens/Duplicates";
import { Outbox } from "./screens/Outbox";
import { CampaignDetail, Campaigns } from "./screens/Campaigns";
import { SendingQueue } from "./screens/SendingQueue";
import { WaitingOnOthers } from "./screens/WaitingOnOthers";
import { Pipeline } from "./screens/Pipeline";
import { ReferralSettings } from "./screens/ReferralSettings";
import { StageRules } from "./screens/StageRules";
import { Staff } from "./screens/Staff";
import { Vendors } from "./screens/Vendors";
import { Activity } from "./screens/Activity";
import { AiUsage } from "./screens/AiUsage";
import { Branding } from "./screens/Branding";
import { Practices } from "./screens/Practices";
import { PlatformFeedback } from "./screens/PlatformFeedback";
import { Dashboard } from "./screens/Dashboard";
import { Meetings } from "./screens/Meetings";
import { Replies } from "./screens/Replies";
import { Notes } from "./screens/Notes";
import { PinReset } from "./screens/PinReset";
import { CadenceLink } from "./screens/CadenceLink";
import { Unsubscribe } from "./screens/Unsubscribe";
import { PreCallForm } from "./screens/PreCallForm";
import { SessionDetail } from "./screens/SessionDetail";
import { SessionTemplate } from "./screens/SessionTemplate";
import { Sessions } from "./screens/Sessions";
import { Digests } from "./screens/Digests";
import { Report } from "./screens/Report";
import { Tasks } from "./screens/Tasks";
import { Work } from "./screens/Work";
import { WorkParentDetail } from "./screens/WorkParentDetail";


const TENANT = ["FF", "CF", "VA"];

const CLIENT = ["FCC", "ECC"];

/** `group` is the heading the item sits under in the sidebar. A flat list of
 *  seventeen links is a list nobody reads; the groups say what each part of the
 *  product is for, and they are the same words the modules use. */
type NavItem = {
  to: string; label: string; roles?: string[]; group?: string;
  /** Every nav item has one (design brief, Tier 1). */
  icon: typeof Users;
};

/** The Practices area's whole navigation (P2). */
const PLATFORM_NAV: NavItem[] = [
  { to: "/practices", label: "Practices", group: "Platform", icon: Building2 },
  { to: "/feedback", label: "Feedback", icon: Inbox },
];

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
  { to: "/waiting", label: "Waiting on others", roles: TENANT , icon: Hourglass },
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
  { to: "/sending-queue", label: "Sending queue", roles: TENANT , icon: Send },
  { to: "/campaigns", label: "Campaigns", roles: TENANT , icon: Megaphone },
  { to: "/outbox", label: "Outbox (send log)", roles: TENANT , icon: Inbox },
  { to: "/import", label: "CSV import", roles: ["FF", "VA"] , icon: Upload },
  { to: "/settings/email", label: "Email settings", roles: ["FF", "CF"] , group: "Settings" , icon: Mail },
  { to: "/settings/branding", label: "Branding", roles: ["FF"] , icon: Palette },
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
    || matchPath("/strategy/precall/:token", location.pathname)
    || matchPath("/unsubscribe/:token", location.pathname);
  if (isPublic) {
    return (
      <Routes>
        <Route path="/updates/:token"
          element={<LinkBranded kind="cadence"><CadenceLink /></LinkBranded>} />
        <Route path="/strategy/precall/:token"
          element={<LinkBranded kind="precall"><PreCallForm /></LinkBranded>} />
        <Route path="/unsubscribe/:token"
          element={<LinkBranded kind="unsubscribe"><Unsubscribe /></LinkBranded>} />
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
  const { data: brand } = useBranding();
  // P2: the Practices area is a staff screen with no practice bound.
  const platform = me?.area === "platform";
  const staff = platform || (!!me?.role && TENANT.includes(me.role));
  // Manual only, and remembered in this browser (design brief, Tier 1).
  const [chosen, setCollapsed] = useRemembered("enhq.sidebar.collapsed", false);
  // Narrow windows collapse it; widening gives it back. The remembered choice
  // is never overwritten, so a deliberate collapse survives both.
  const narrow = useNarrowWindow();
  const collapsed = chosen || narrow;
  const wordmark = (staff ? brand?.product_name : brand?.display_name) ?? "";
  const palette = brand?.palette;

  // P1: a client's portal wears the practice's whole color family; staff
  // screens keep the product's look, so their tokens are removed, not set.
  useEffect(() => {
    if (!palette) return;
    applyPortalTokens(document.documentElement,
      staff ? null : { primary: palette.header, accent: palette.accent });
  }, [palette, staff]);

  useEffect(() => {
    if (wordmark) document.title = wordmark;
  }, [wordmark]);

  // The tab icon: the product's for staff, the practice's mark (or its
  // initials) for everyone else. In production the server already wrote the
  // right one into index.html (config/spa.py); this keeps the dev server and
  // a sign-in within the page right.
  useEffect(() => {
    if (!brand) return;
    // Signed out, no practice is known: the product's icon (P2).
    setFavicon(staff || !brand.mark_url ? PRODUCT_FAVICON : brand.mark_url);
  }, [brand, staff]);

  if (isLoading) return <main style={{ padding: "2rem" }}>Loading…</main>;

  if (isError || !me?.authenticated) {
    return <SignedOut practice={brand?.display_name || ""} />;
  }

  // P2: a practice owner reads and accepts the beta agreement before anything
  // else; the server refuses every other call until then.
  if (me.agreement_required) return <AgreementGate />;

  const visible = platform ? PLATFORM_NAV
    : NAV.filter((n) => !n.roles || (me.role && n.roles.includes(me.role)));

  return (
    <div className={collapsed ? "layout collapsed" : "layout"}>
      <aside className="sidebar">
        <div className="brand">
          {brand?.logo_url && !staff
            ? <img src={brand.logo_url} alt={wordmark} />
            : <h1>{wordmark}</h1>}
          {/* P1: staff see which practice they are in, under the product. */}
          {staff && brand?.display_name && (
            <div className="practice" aria-label="Practice">{brand.display_name}</div>)}
        </div>
        {/* Its own block, above the New note button: inside the brand block it
            overflowed under the button and the dropdown could not be reached. */}
        <AreaSwitch me={me} />
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
        <button className="collapse"
          aria-label={collapsed ? "Expand the menu" : "Collapse the menu"}
          // On a narrow window the toggle expands over the content rather than
          // fighting the width: the choice it writes is still the manual one.
          onClick={() => setCollapsed(!chosen)}>
          {collapsed ? <PanelLeftOpen size={18} strokeWidth={1.75} />
            : <><PanelLeftClose size={18} strokeWidth={1.75} /> <span>Collapse</span></>}
        </button>
        <div className="who">
          <Avatar name={me.full_name || me.email} size="lg" />
          <div className="names" style={{ minWidth: 0 }}>
            <div className="name">{me.full_name || me.email}</div>
            <div className="role">{platform ? "Platform owner" : roleLabel(me.role)}</div>
            <ActAsColleague me={me} />
          </div>
        </div>
      </aside>
      <main>
        {/* FR-3.42 — never dismissible; stopping is the only way out. */}
        <ActingBanner me={me} />
        <DemoBanner me={me} />
        <ErrorBoundary>
          {me.role && TENANT.includes(me.role) && <PendingUploads />}
          {/* P2 §7: on every staff screen in a practice. Clients never see it. */}
          {me.role && TENANT.includes(me.role) && <FeedbackButton />}
          {platform ? (
            <Routes>
              <Route path="/feedback" element={<PlatformFeedback />} />
              <Route path="*" element={<Practices />} />
            </Routes>
          ) : (
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
            <Route path="/contacts/duplicates" element={<Duplicates />} />
            <Route path="/pipeline" element={<Pipeline />} />
            <Route path="/companies" element={<Companies me={me} />} />
            <Route path="/companies/:id" element={<CompanyDetail me={me} />} />
            <Route path="/vendors" element={<Vendors />} />
            <Route path="/sending-queue" element={<SendingQueue me={me} />} />
            <Route path="/waiting" element={<WaitingOnOthers />} />
            <Route path="/campaigns" element={<Campaigns />} />
            <Route path="/campaigns/:id" element={<CampaignDetail />} />
            <Route path="/outbox" element={<Outbox />} />
            <Route path="/import" element={<ImportWizard />} />
            <Route path="/settings/email" element={<EmailSettings me={me} />} />
            <Route path="/settings/branding" element={<Branding />} />
            <Route path="/referrals" element={<ReferralSettings />} />
            <Route path="/rules" element={<StageRules />} />
            <Route path="/staff" element={<Staff me={me} />} />
            <Route path="/ai-usage" element={<AiUsage />} />
            <Route path="/notes" element={<Notes me={me} />} />
            <Route path="/notes/pin-reset/:token" element={<PinReset />} />
            {/* The panel owns both: a link into one note still opens it, and
                opens it beside the list rather than instead of it. */}
            <Route path="/notes/:id" element={<Notes me={me} />} />
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
          )}
        </ErrorBoundary>
        <ToastHost />
      </main>
    </div>
  );
}
