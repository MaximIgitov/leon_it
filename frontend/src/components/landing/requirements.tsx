import { Globe, Laptop, Timer, Wifi } from "lucide-react";

import { IconChip, Section } from "@/components/landing/section";

/*
 * Матрица браузеров — из проверки устройств в комнате (lib/media/devices.ts):
 * Chrome, Firefox, Edge, Safari, Яндекс Браузер, Samsung Internet; на iPhone и
 * iPad запись работает в Safari.
 */
const REQUIREMENTS = [
  {
    icon: Laptop,
    title: "Устройство с камерой и микрофоном",
    items: [
      "Ноутбук или компьютер с веб-камерой — удобнее всего.",
      "Смартфон тоже подходит: поставьте его на подставку на уровне глаз, экран во время записи не погаснет.",
      "Гарнитура или наушники с микрофоном дают более чистый звук.",
    ],
  },
  {
    icon: Globe,
    title: "Актуальный браузер",
    items: [
      "На компьютере: Chrome, Firefox, Edge или Safari последних версий. Яндекс Браузер тоже работает.",
      "На iPhone и iPad — Safari: в других браузерах iOS запись может быть ограничена.",
      "На Android — Chrome или Samsung Internet.",
      "Ссылка открывается по https — так браузер разрешает доступ к камере.",
    ],
  },
  {
    icon: Wifi,
    title: "Устойчивое соединение",
    items: [
      "Домашний Wi-Fi или мобильный интернет с хорошим сигналом.",
      "Закройте Zoom, Teams и другие вкладки с видеозвонками — иначе камера будет занята.",
      "Если связь оборвётся, сохранённые ответы не пропадут: вернётесь по той же ссылке.",
    ],
  },
  {
    icon: Timer,
    title: "Тихое место и 10–20 минут",
    items: [
      "Точное число вопросов и время — на странице приглашения.",
      "Свет спереди, а не за спиной; лицо целиком в кадре.",
      "Предупредите домашних и уберите уведомления: уход со вкладки во время ответа фиксируется.",
    ],
  },
] as const;

export function Requirements() {
  return (
    <Section
      id="requirements"
      eyebrow="Что нужно для интервью"
      title="Подготовьте место и устройство заранее"
      lead="Проверка камеры и микрофона перед стартом покажет, всё ли в порядке. Но пять минут подготовки сэкономят нервы."
    >
      <div className="grid gap-4 sm:grid-cols-2">
        {REQUIREMENTS.map((block) => (
          <article key={block.title} className="rounded-2xl border bg-card p-6 shadow-sm">
            <div className="flex items-center gap-3">
              <IconChip icon={block.icon} />
              <h3 className="text-lg font-semibold">{block.title}</h3>
            </div>
            <ul className="mt-4 space-y-2 text-sm text-muted-foreground">
              {block.items.map((item) => (
                <li key={item} className="flex gap-2">
                  <span aria-hidden="true" className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full bg-primary" />
                  <span>{item}</span>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </Section>
  );
}
