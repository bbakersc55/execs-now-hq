import { useState } from "react";

import { Me, api } from "../lib/api";

/**
 * The platform owner's switch between their own practice and the Practices
 * area (P2, owner 2026-10-02): one sign-in, two areas, and always clear which
 * one you are in. Anyone else never sees it.
 */
export function AreaSwitch({ me }: { me: Me }) {
  const [busy, setBusy] = useState(false);
  if (!me.is_platform_owner) return null;
  const area = me.area === "platform" ? "platform" : "practice";

  async function go(next: string) {
    if (next === area) return;
    setBusy(true);
    try {
      await api.post("/api/platform/area", { area: next });
      // A full load: every query, color and icon changes with the area.
      window.location.assign(next === "platform" ? "/practices" : "/");
    } finally {
      setBusy(false);
    }
  }

  return (
    <label className="area-switch">
      <select aria-label="Area" value={area} disabled={busy}
        onChange={(e) => go(e.target.value)}>
        <option value="practice">{me.home_practice || "Your practice"}</option>
        <option value="platform">Practices</option>
      </select>
    </label>
  );
}
