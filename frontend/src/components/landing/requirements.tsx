import { Camera, Coffee, Wifi } from "lucide-react";
export function Requirements() {
  return <section id="requirements" className="requirements-strip" aria-label="Что подготовить к интервью"><div><span className="section-kicker">ДЛЯ ХОРОШЕГО РАЗГОВОРА</span><h2>Устройся поудобнее</h2></div><span><Camera /> Камера и микрофон</span><span><Wifi /> Стабильный интернет</span><span><Coffee /> Немного тишины</span></section>;
}
