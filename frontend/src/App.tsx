import { useQuery } from "@tanstack/react-query";

interface Branding {
  product_name: string;
  palette: Record<string, string>;
}

export function App() {
  const { data, isLoading } = useQuery<Branding>({
    queryKey: ["branding"],
    queryFn: async () => {
      const response = await fetch("/api/branding");
      if (!response.ok) throw new Error("branding unavailable");
      return response.json();
    },
  });

  if (isLoading) return <main style={{ padding: "2rem" }}>Loading…</main>;

  return (
    <main style={{ padding: "2rem" }}>
      <h1>{data?.product_name}</h1>
      <p style={{ color: "var(--brand-gray-dark)" }}>
        Phase 0.5 foundation. Tenancy, auth, and the two test registries.
      </p>
    </main>
  );
}
