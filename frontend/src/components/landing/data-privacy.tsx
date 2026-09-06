import Link from "@/lib/router";
import { ArrowUpRight, ShieldCheck, UserRoundCheck } from "lucide-react";
export function DataPrivacy() {
  return <section id="privacy" className="privacy-strip" aria-label="Данные и решение"><div><ShieldCheck /><p><strong>Твои ответы — для команды найма.</strong><span>Доступ ограничен ролями и сроком хранения.</span></p></div><div><UserRoundCheck /><p><strong>ИИ помогает. Решает человек.</strong><span>Оценка по ответам, а не по внешности.</span></p></div><Link href="/legal/privacy-policy">О данных <ArrowUpRight size={16} /></Link></section>;
}
