import { useQueryClient } from "@tanstack/react-query";
import { PanelLeftClose, PanelLeftOpen } from "lucide-react";
import { KeyboardEvent, ReactNode, useEffect, useRef, useState } from "react";

import { Me, api } from "../lib/api";
import { roleLabel } from "../lib/roles";
import { ActAsColleague } from "./ActAs";
import { FeedbackButton } from "./FeedbackButton";
import { Avatar } from "./shell";

/**
 * The bar across the top of every signed-in screen (UI 3 spec §2).
 *
 * It took three things out of the sidebar: the collapse button, the block
 * naming who is signed in, and (through the profile menu) Settings. It also
 * holds the one thing the app never had: a way to sign out.
 */
export function TopBar({ me, practice, collapsed, onToggleSidebar, feedback }: {
  me: Me;
  /** The practice's name, for the menu's header. */
  practice: string;
  collapsed: boolean; onToggleSidebar: () => void;
  /** Staff in a practice send feedback; clients and the Practices area do not. */
  feedback: boolean;
}) {
  return (
    <header className="topbar" aria-label="Top bar">
      <button className="icon-button"
        aria-label={collapsed ? "Expand the menu" : "Collapse the menu"}
        onClick={onToggleSidebar}>
        {collapsed ? <PanelLeftOpen size={18} strokeWidth={1.75} />
          : <PanelLeftClose size={18} strokeWidth={1.75} />}
      </button>
      <div className="right">
        {feedback && <FeedbackButton />}
        <ProfileMenu me={me} practice={practice} />
      </div>
    </header>
  );
}

function ProfileMenu({ me, practice }: { me: Me; practice: string }) {
  const qc = useQueryClient();
  const [open, setOpen] = useState(false);
  const [leaving, setLeaving] = useState(false);
  const wrap = useRef<HTMLDivElement>(null);
  const button = useRef<HTMLButtonElement>(null);
  const name = me.full_name || me.email;
  const role = me.area === "platform" ? "Platform owner" : roleLabel(me.role);

  const items = () => Array.from(
    wrap.current?.querySelectorAll<HTMLElement>('[role="menuitem"]') ?? []);

  useEffect(() => {
    if (!open) return;
    items()[0]?.focus();
    const away = (e: PointerEvent) => {
      if (!wrap.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [open]);

  function onKeyDown(e: KeyboardEvent) {
    if (!open) return;
    if (e.key === "Escape") {
      setOpen(false);
      button.current?.focus();
    } else if ((e.key === "ArrowDown" || e.key === "ArrowUp")
               && (e.target as HTMLElement).getAttribute("role") === "menuitem") {
      e.preventDefault();
      const all = items();
      const at = all.indexOf(document.activeElement as HTMLElement);
      all[(at + (e.key === "ArrowDown" ? 1 : -1) + all.length) % all.length]?.focus();
    }
  }

  async function signOut() {
    setLeaving(true);
    try {
      await api.post("/auth/sign-out");
    } finally {
      // Whatever the answer, nothing cached may outlive the session.
      qc.clear();
      window.location.assign("/");
    }
  }

  return (
    <div className="profile" ref={wrap} onKeyDown={onKeyDown}>
      <button ref={button} type="button" className="profile-button"
        aria-label={`Your account: ${name}`} aria-haspopup="menu" aria-expanded={open}
        onClick={() => setOpen((o) => !o)}>
        <Avatar name={name} size="lg" />
      </button>
      {open && (
        <div className="profile-menu" role="menu" aria-label="Your account">
          <div className="who">
            <div className="name">{name}</div>
            <div className="role">{role}{practice && ` · ${practice}`}</div>
          </div>
          <MenuExtras me={me} />
          <button type="button" role="menuitem" className="sign-out" disabled={leaving}
            onClick={signOut}>
            {leaving ? "Signing out…" : "Sign out"}
          </button>
        </div>
      )}
    </div>
  );
}

/** A client owner's "Act as a colleague", as it was in the sidebar. Not a
 *  menu item: it is a picker, and stays one. */
function MenuExtras({ me }: { me: Me }): ReactNode {
  if (me.role !== "FCC" || me.acting) return null;
  return <div className="extra"><ActAsColleague me={me} /></div>;
}
