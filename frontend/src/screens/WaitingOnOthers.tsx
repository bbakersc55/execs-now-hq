import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { Search } from "lucide-react";

import { CommitmentList } from "../components/CommitmentList";
import { Chip, FilterBar, PageHead } from "../components/shell";
import { Card, Empty } from "../components/ui";
import { Commitment, api } from "../lib/api";

/**
 * Waiting on others (owner, 2026-09-28): every open commitment someone
 * outside the practice made in a meeting — who, what, by when, when we look
 * again, and where it came from. Staff only.
 */
export function WaitingOnOthers() {
  const [q, setQ] = useState("");
  const [state, setState] = useState<"open" | "done" | "all">("open");
  const [overdue, setOverdue] = useState(false);
  const query = new URLSearchParams({ state, ...(q.trim() ? { q: q.trim() } : {}),
                                      ...(overdue ? { overdue: "1" } : {}) });
  const rows = useQuery<Commitment[]>({
    queryKey: ["commitments", query.toString()],
    queryFn: () => api.get<Commitment[]>(`/api/commitments/?${query}`),
  });
  const list = rows.data ?? [];

  return (
    <>
      <PageHead title="Waiting on others"
        sub="What people outside the practice said they would do, from your meetings — and
             when you look again." />
      <FilterBar onClearAll={q || overdue || state !== "open"
        ? () => { setQ(""); setOverdue(false); setState("open"); } : undefined}>
        <span className="search">
          <Search size={16} strokeWidth={1.75} />
          <input aria-label="Search commitments" placeholder="Person, company or what"
            value={q} onChange={(e) => setQ(e.target.value)} />
        </span>
        <select aria-label="Which" value={state} className="filter-select"
          onChange={(e) => setState(e.target.value as typeof state)}>
          <option value="open">Open</option>
          <option value="done">Done</option>
          <option value="all">All</option>
        </select>
        {!overdue && <button className="small" onClick={() => setOverdue(true)}>Overdue only</button>}
        {overdue && <Chip label="Overdue only" onClear={() => setOverdue(false)} />}
      </FilterBar>
      <Card>
        {list.length === 0
          ? <Empty>{state === "open" ? "Nobody owes you anything right now." : "Nothing here."}</Empty>
          : <CommitmentList rows={list} />}
      </Card>
    </>
  );
}
