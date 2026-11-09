import { SITE_URL } from "../config";

export function GET() {
  return new Response(`User-agent: *\nAllow: /\nDisallow: /demo/thanks\nDisallow: /demo/error\n\nSitemap: ${SITE_URL}/sitemap.xml\n`, {
    headers: { "Content-Type": "text/plain" },
  });
}
