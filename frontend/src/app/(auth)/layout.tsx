import Link from "@/lib/router";
import { ArrowLeft } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { ThemeSwitch } from "@/components/ui/theme-switch";
import { Mascot } from "@/components/brand/mascot";

export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return <div className="auth-page"><header className="simple-header"><Link href="/" aria-label="LeonIT — на главную"><Logo size={40} /></Link><div className="header-actions"><ThemeSwitch /><Link href="/" className="header-back"><ArrowLeft size={14} />На главную</Link></div></header><main className="auth-main"><aside className="auth-story"><h2>Знакомьтесь<br />с кандидатами.</h2><Mascot name="mira" eager /></aside><div className="auth-card">{children}</div></main></div>;
}
