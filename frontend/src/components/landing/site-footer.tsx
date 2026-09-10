import Link from "@/lib/router";
import { Logo } from "@/components/brand/logo";
import { CONTACT_EMAIL, LEGAL_DOCUMENTS, legalHref } from "@/lib/site";
export function SiteFooter() {
  return <footer className="site-footer"><div className="footer-main"><div><Link href="/" aria-label="LeonIT — главная"><Logo size={38} /></Link><p>В каждом человеке — новый потенциал.</p></div><a className="footer-email" href={`mailto:${CONTACT_EMAIL}`}>Давай на связи ↗<span>{CONTACT_EMAIL}</span></a></div><div className="footer-legal"><span>© {new Date().getFullYear()} LeonIT</span><nav aria-label="Юридические документы">{LEGAL_DOCUMENTS.map(doc => <Link key={doc.slug} href={legalHref(doc.slug)}>{doc.title}</Link>)}</nav></div></footer>;
}
