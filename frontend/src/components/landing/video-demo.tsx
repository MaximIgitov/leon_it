import { useState } from "react";
import Link from "@/lib/router";
import { ArrowRight, AudioLines, Play } from "lucide-react";
import { Mascot } from "@/components/brand/mascot";
import { Button } from "@/components/ui/button";

export const DEMO_VIDEO_SRC = "/demo/interview-demo.mp4";
export const DEMO_POSTER_SRC = "/demo/poster.svg";

export function VideoDemo({ available = true }: { available?: boolean }) {
  const [playing, setPlaying] = useState(false);
  return <section id="demo" className="landing-section" aria-labelledby="demo-title">
    <div className="practice-preview">
      <div className="practice-preview-stage">
        {playing && available ? <video src={DEMO_VIDEO_SRC} controls autoPlay playsInline className="practice-preview-video" aria-label="Видео: полный сценарий интервью" onError={() => setPlaying(false)} /> : <>
          <div className="practice-preview-person"><Mascot name="leo" /><span>Леон</span></div>
          <div className="practice-preview-question"><AudioLines size={25} aria-hidden /><p>Над каким проектом тебе понравилось работать?</p></div>
          <div className="practice-preview-caption"><span className="mini-wave" aria-hidden><i /><i /><i /><i /><i /></span><span>Пробный вопрос</span>{available && <button onClick={() => setPlaying(true)} aria-label="Посмотреть видео интервью"><Play size={18} fill="currentColor" /></button>}</div>
        </>}
      </div>
      <div className="practice-preview-copy"><h2 id="demo-title">Попробуй<br />один вопрос</h2><p>Познакомься с Леоном, проверь камеру и запиши пробный ответ.</p><Button size="lg" variant="outline" asChild><Link href="/practice">Начать тренировку <ArrowRight size={19} /></Link></Button><span>Запись останется в твоём браузере.</span></div>
    </div>
  </section>;
}
