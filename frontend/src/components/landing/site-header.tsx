import Link from "@/lib/router";
import { ArrowUpRight } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { ThemeSwitch } from "@/components/ui/theme-switch";

export const LANDING_NAV = [
  { href: "#how-it-works", label: "Как это работает" },
  { href: "#recruiters", label: "Для команд" },
  { href: "#faq", label: "Вопросы" },
];

export function SiteHeader() {
  return <header className="site-header">
    <a href="#main" className="skip-link">К содержимому</a>
    <div className="site-header-inner">
      <Link href="/" aria-label="LeonIT — главная"><Logo size={42} /></Link>
      <nav aria-label="По странице" className="landing-nav">{LANDING_NAV.map(item => <a key={item.href} href={item.href}>{item.label}</a>)}</nav>
      <div className="header-actions"><ThemeSwitch /><Button variant="outline" asChild className="header-login"><Link href="/login">Войти <ArrowUpRight size={17} aria-hidden /></Link></Button></div>
    </div>
  </header>;
}
