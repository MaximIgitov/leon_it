import Link from "@/lib/router";
import { useEffect, useRef, useState } from "react";
import { ArrowLeft, ArrowRight, Camera, LockKeyhole, RotateCcw, Timer } from "lucide-react";
import { Logo } from "@/components/brand/logo";
import { ThemeSwitch } from "@/components/ui/theme-switch";
import { Mascot } from "@/components/brand/mascot";
import { DeviceCheck, type DeviceCheckResult } from "@/components/interview/device-check";
import { PracticeQuestion } from "@/components/interview/practice";
import { Button } from "@/components/ui/button";
import { stopStream } from "@/lib/media/devices";

export default function PracticePage() {
  const [step, setStep] = useState<"intro" | "devices" | "question" | "done">("intro");
  const [devices, setDevices] = useState<DeviceCheckResult | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  useEffect(() => () => stopStream(streamRef.current), []);

  const finish = () => {
    stopStream(streamRef.current);
    streamRef.current = null;
    setDevices(null);
    setStep("done");
  };

  return <div className="interview-page">
    <header className="simple-header"><Link href="/" aria-label="LeonIT — главная"><Logo size={38} /></Link><div className="header-actions"><ThemeSwitch /><Link href="/" className="header-back"><ArrowLeft size={14} />На главную</Link></div></header>
    <main className="interview-main"><div className={`interview-card ${step === "devices" || step === "question" ? "interview-card-wide" : ""}`}>
      {step === "intro" && <div className="practice-intro"><span className="eyebrow-pill">ЗНАКОМСТВО С ЛЕОНОМ</span><Mascot name="leo" eager /><h1>Давай начнём<br />с простого.</h1><p>Один пробный вопрос, чтобы освоиться.<br />Без оценок. В твоём темпе.</p><Button size="lg" onClick={() => setStep("devices")}><Camera size={19} /> Проверить камеру <ArrowRight size={18} /></Button><div className="practice-perks"><span><Timer /> Пара минут</span><span><LockKeyhole /> Запись только у тебя</span></div></div>}
      {step === "devices" && <div className="space-y-6"><div className="practice-question-heading"><Mascot name="mira" /><div><h1 className="text-2xl">Тебя видно и слышно?</h1><p>Проверим технику — и можно знакомиться.</p></div></div><DeviceCheck onReady={result => { streamRef.current = result.stream; setDevices(result); setStep("question"); }} /></div>}
      {step === "question" && devices && <PracticeQuestion stream={devices.stream} onDone={finish} doneLabel="Завершить тренировку" />}
      {step === "done" && <div className="interview-finished"><Mascot name="celebrate" eager /><h1>Тренировка завершена</h1><p>Для интервью открой ссылку от рекрутера. Пробная запись осталась в браузере.</p><div className="flex flex-wrap justify-center gap-3"><Button size="lg" asChild><Link href="/">На главную <ArrowRight size={18} /></Link></Button><Button size="lg" variant="outline" onClick={() => setStep("devices")}><RotateCcw size={17} /> Ещё раз</Button></div></div>}
    </div></main>
    <p className="auth-footnote"><LockKeyhole size={12} className="inline mr-1" /> Тренировка проходит только в твоём браузере</p>
  </div>;
}
