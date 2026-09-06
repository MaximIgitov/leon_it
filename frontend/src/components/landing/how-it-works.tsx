import { Camera, Check, Link2 } from "lucide-react";
import { Mascot } from "@/components/brand/mascot";

const steps = [
  { number: "01", title: "Открой приглашение", text: "Перейди по ссылке от команды.", name: "fox" as const, icon: Link2, tone: "green", chip: "Ты приглашён!" },
  { number: "02", title: "Расскажи о себе", text: "Проверь камеру и отвечай как в беседе.", name: "rabbit" as const, icon: Camera, tone: "orange", chip: "Леон слушает" },
  { number: "03", title: "Сделай следующий шаг", text: "Команда посмотрит ответы и свяжется с тобой.", name: "bear" as const, icon: Check, tone: "cream", chip: "Всё получилось" },
];

export function HowItWorks() {
  return <section id="how-it-works" className="landing-section" aria-labelledby="how-it-works-title">
    <div className="section-heading"><h2 id="how-it-works-title">Всего три простых шага</h2></div>
    <ol className="steps-grid">{steps.map(step => <li key={step.number} className={`step-card step-${step.tone}`}>
      <div className="step-card-top"><span className="step-number">{step.number}</span></div>
      <div className="step-visual"><Mascot name={step.name} /><span className="step-chip"><step.icon size={16} />{step.chip}</span></div>
      <h3>{step.title}</h3><p>{step.text}</p>
    </li>)}</ol>
  </section>;
}
