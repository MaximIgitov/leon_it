import type { MetadataRoute } from "next";

import { SITE_URL } from "@/lib/site";

/*
 * Страницы кандидата (/i/), отчётов по ссылке (/r/) и приглашений в
 * организацию (/join) не индексируются: они персональные и защищены токенами.
 */
export default function robots(): MetadataRoute.Robots {
  return {
    rules: [{ userAgent: "*", allow: "/", disallow: ["/i/", "/r/", "/join"] }],
    sitemap: `${SITE_URL}/sitemap.xml`,
  };
}
