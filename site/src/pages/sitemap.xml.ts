import { SITE_URL, LEGAL_DRAFT } from "../config";

// The legal pages join the sitemap once they are no longer drafts.
const PAGES = ["/", "/pricing", "/security", "/about", "/demo", "/changelog",
  ...(LEGAL_DRAFT ? [] : ["/privacy", "/terms"])];

export function GET() {
  const body = `<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
${PAGES.map((p) => `  <url><loc>${SITE_URL}${p === "/" ? "/" : p}</loc></url>`).join("\n")}
</urlset>
`;
  return new Response(body, { headers: { "Content-Type": "application/xml" } });
}
