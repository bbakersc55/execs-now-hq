import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link } from "react-router-dom";

import { Card, Empty, Pill } from "../components/ui";
import { api, Contact } from "../lib/api";

interface Category { id: string; name: string; }

export function Vendors() {
  const qc = useQueryClient();
  const [category, setCategory] = useState("");
  const [newCategory, setNewCategory] = useState("");

  const categories = useQuery<Category[]>({
    queryKey: ["categories"], queryFn: () => api.get<Category[]>("/api/service-categories/"),
  });
  const results = useQuery<Contact[]>({
    queryKey: ["vendors", category],
    queryFn: () => api.get<Contact[]>(`/api/contacts/by-category/?category=${encodeURIComponent(category)}`),
    enabled: category.length > 0,
  });

  const add = useMutation({
    mutationFn: () => api.post("/api/service-categories/", { name: newCategory }),
    onSuccess: () => { setNewCategory(""); qc.invalidateQueries({ queryKey: ["categories"] }); },
  });

  return (
    <>
      <h2>Vendors</h2>
      <p className="sub">Find a vendor by what they do, for when a client asks.</p>

      <Card title="Search by service category">
        <div className="row">
          <div style={{ flex: "2 1 240px" }}>
            <select value={category} onChange={(e) => setCategory(e.target.value)}>
              <option value="">Choose a category…</option>
              {(categories.data ?? []).map((c) => <option key={c.id} value={c.name}>{c.name}</option>)}
            </select>
          </div>
          <div style={{ flex: "2 1 240px" }}>
            <input placeholder="Add a new category" value={newCategory}
              onChange={(e) => setNewCategory(e.target.value)} />
          </div>
          <div style={{ flex: "0 0 auto" }}>
            <button disabled={!newCategory} onClick={() => add.mutate()}>Add category</button>
          </div>
        </div>
      </Card>

      {category && (
        <Card title={`Vendors in “${category}”`}>
          {(results.data ?? []).length === 0 ? <Empty>No vendors in this category.</Empty> : (
            <table>
              <thead><tr><th>Name</th><th>Title</th><th>Types</th></tr></thead>
              <tbody>
                {results.data!.map((v) => (
                  <tr key={v.id}>
                    <td><Link to={`/contacts/${v.id}`}>{v.first_name} {v.last_name}</Link></td>
                    <td className="muted">{v.title || "—"}</td>
                    <td>{v.type_codes.map((t) => <Pill key={t}>{t.replace(/_/g, " ")}</Pill>)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      )}
    </>
  );
}
