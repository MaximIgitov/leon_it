import Link from "@/lib/router";
import { ArrowRight, AudioLines, Check, Clock3, Play, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

export function Hero() {
  return <section className="hero-section" aria-labelledby="hero-title">
    <div className="hero-copy">
      <h1 id="hero-title">Познакомься<br />с будущей<br /><span className="hero-green">командой<span className="orange-dot">.</span></span></h1>
      <p className="hero-description">Пройди интервью с Леоном в удобное время.<br className="desktop-break" /> Расскажи об опыте и своих проектах.</p>
      <div className="hero-actions">
        <Button size="lg" asChild><Link href="/practice">Попробовать интервью <ArrowRight size={20} aria-hidden /></Link></Button>
        <a href="#demo" className="demo-link"><span><Play size={14} fill="currentColor" aria-hidden /></span> Как это выглядит</a>
      </div>
    </div>
    <div className="hero-art" aria-label="Леон и его команда — дружелюбные персонажи интервью" role="img">
      <img src="/brand/hero-team.png" width={1536} height={1024} alt="" className="hero-team" fetchPriority="high" decoding="async" draggable={false} />
      <div className="hero-star star-one"><Sparkles size={36} strokeWidth={2.5} /></div>
      <span className="hero-star star-two">✳</span>
      <div className="speech-bubble bubble-hello">Привет! Я Леон <span aria-hidden>✌️</span></div>
      <div className="speech-bubble bubble-answer"><span className="mini-wave"><i /><i /><i /><i /><i /></span> Просто будь собой</div>
      <span className="art-sticker sticker-clock"><Clock3 size={21} /> В твоём ритме</span>
      <span className="art-sticker sticker-check"><Check size={24} strokeWidth={3} /></span>
    </div>
    <div className="hero-bottom">
      <div className="benefits-ticker">
        <div className="benefits-track">{[0, 1].map(copy => <div className="benefits-group" key={copy} aria-hidden={copy === 1 ? true : undefined}>
          <span><AudioLines size={20} /> Живой разговор с ИИ</span>
          <span><Clock3 size={20} /> Когда удобно тебе</span>
          <span><Check size={20} /> Решение за человеком</span>
        </div>)}</div>
      </div>
    </div>
  </section>;
}
