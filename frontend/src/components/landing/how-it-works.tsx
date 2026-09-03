import { Camera, CircleCheck, FileCheck2, GraduationCap, Link2, MessageSquareText, RotateCcw } from "lucide-react";

import { IconChip, Section } from "@/components/landing/section";

/*
 * Шаги совпадают с реальной комнатой (app/i/[token], components/interview):
 * приглашение → согласия → проверка устройств → тренировочный вопрос →
 * вопросы по одному → завершение.
 */
const STEPS = [
  {
    icon: Link2,
    title: "Откройте ссылку из письма",
    text: "На странице приглашения — название вакансии, сколько вопросов, сколько это займёт и до какого числа нужно пройти. Никакой регистрации: только имя и e-mail.",
  },
  {
    icon: FileCheck2,
    title: "Подтвердите согласия",
    text: "Два обязательных чекбокса: согласие на обработку данных, включая видео и голос, и знакомство с политикой конфиденциальности. Рассылка — по желанию, галочка не стоит заранее.",
  },
  {
    icon: Camera,
    title: "Проверьте камеру и микрофон",
    text: "Выберите устройства, скажите пару слов — индикатор покажет уровень звука. Запишите пробные 5 секунд и убедитесь, что вас видно и слышно. Если браузер не даёт доступ, страница подскажет, где его включить.",
  },
  {
    icon: GraduationCap,
    title: "Разомнитесь на тренировочном вопросе",
    text: "Ответ остаётся у вас в браузере и никуда не отправляется. Так вы привыкнете к формату до первого настоящего вопроса. Шаг можно пропустить.",
  },
  {
    icon: MessageSquareText,
    title: "Отвечайте на вопросы по одному",
    text: "Нажмите «Показать вопрос» — он появится на экране и будет озвучен. Есть время на подготовку (можно начать раньше), затем идёт запись с таймером. Закончили — «Завершить ответ», и запись сохраняется.",
  },
  {
    icon: CircleCheck,
    title: "Завершите интервью",
    text: "После последнего ответа вы увидите «Спасибо, интервью завершено!». Ответы уже у рекрутера, о результате вам напишут на e-mail.",
  },
] as const;

export function HowItWorks() {
  return (
    <Section
      id="how"
      eyebrow="Как проходит интервью"
      title="Шесть шагов от ссылки до «Спасибо, интервью завершено»"
      lead="Всё происходит в браузере на одной странице. Ничего не нужно устанавливать, а прерваться и вернуться можно по той же ссылке."
    >
      <ol className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {STEPS.map((step, index) => (
          <li key={step.title} className="relative rounded-2xl border bg-card p-6 shadow-sm">
            <div className="flex items-center justify-between">
              <IconChip icon={step.icon} />
              <span className="font-mono text-sm text-muted-foreground" aria-label={`Шаг ${index + 1}`}>
                0{index + 1}
              </span>
            </div>
            <h3 className="mt-4 text-lg font-semibold">{step.title}</h3>
            <p className="mt-2 text-sm text-muted-foreground">{step.text}</p>
          </li>
        ))}
      </ol>
      <div className="mt-6 flex items-start gap-3 rounded-2xl border border-primary/20 bg-primary/5 p-5 text-sm">
        <RotateCcw className="mt-0.5 h-4 w-4 shrink-0 text-primary" aria-hidden="true" />
        <p>
          <span className="font-semibold">Перезапись — по настройке вакансии.</span> Если рекрутер разрешил
          повторные попытки, после сохранения ответа появится кнопка «Перезаписать» и счётчик оставшихся
          попыток. Если нет — у каждого вопроса одна попытка, как на живом собеседовании.
        </p>
      </div>
    </Section>
  );
}
