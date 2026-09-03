import type { MetadataRoute } from "next";

import { LEGAL_DOCUMENTS, SITE_URL, legalHref } from "@/lib/site";

/** Публичные страницы: главная и юридические документы. */
export default function sitemap(): MetadataRoute.Sitemap {
  const lastModified = new Date();
  return [
    { url: `${SITE_URL}/`, lastModified, changeFrequency: "monthly", priority: 1 },
    ...LEGAL_DOCUMENTS.map((doc) => ({
      url: `${SITE_URL}${legalHref(doc.slug)}`,
      lastModified,
      changeFrequency: "yearly" as const,
      priority: 0.3,
    })),
  ];
}
