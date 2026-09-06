import { SITE_URL } from "@/lib/site";

export default function robots() {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/i/", "/r/", "/join", "/unsubscribe/"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
