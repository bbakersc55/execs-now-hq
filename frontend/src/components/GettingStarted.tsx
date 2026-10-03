import { useQuery } from "@tanstack/react-query";
import { Link } from "react-router-dom";

import { api } from "../lib/api";
import { Card } from "./ui";

interface Item { key: string; label: string; to: string; done: boolean }

/** P2: the practice owner's Getting started list. Each item is worked out
 *  from the practice's own data, so it ticks itself; the card goes away when
 *  every item is done. */
export function GettingStarted() {
  const { data } = useQuery<Item[]>({
    queryKey: ["getting-started"], queryFn: () => api.get<Item[]>("/api/getting-started"),
  });
  if (!data || data.every((i) => i.done)) return null;
  const left = data.filter((i) => !i.done).length;
  return (
    <Card title={`Getting started · ${data.length - left} of ${data.length} done`}>
      <ul aria-label="Getting started" style={{ listStyle: "none", padding: 0, margin: 0 }}>
        {data.map((i) => (
          <li key={i.key} style={{ padding: "0.3rem 0" }}>
            <span aria-hidden="true" style={{ display: "inline-block", width: "1.4rem" }}>
              {i.done ? "✓" : "○"}</span>
            {i.done ? <span className="muted">{i.label}</span>
              : <Link to={i.to}>{i.label}</Link>}
          </li>
        ))}
      </ul>
    </Card>
  );
}
