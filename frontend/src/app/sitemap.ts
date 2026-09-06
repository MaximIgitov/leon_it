import { LEGAL_DOCUMENTS, SITE_URL, legalHref } from "@/lib/site";

export default function sitemap() {
  const lastModified = new Date();
  return [
    { url: `${SITE_URL}/`, lastModified, changeFrequency: "monthly", priority: 1 },
    ...LEGAL_DOCUMENTS.map((document) => ({
      url: `${SITE_URL}${legalHref(document.slug)}`,
      lastModified,
      changeFrequency: "yearly",
      priority: 0.3,
    })),
  ];
}
