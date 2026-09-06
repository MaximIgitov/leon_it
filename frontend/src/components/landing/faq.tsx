import { Accordion } from "@heroui/react";
import { Mascot } from "@/components/brand/mascot";
export const FAQ_ITEMS = [
  { question: "Как подготовиться?", answer: "Попробуй тренировочный вопрос и проверь камеру. Пробная запись останется в браузере. Время на подготовку к вопросам настоящего интервью задаёт рекрутер." },
  { question: "Нужно устанавливать приложение?", answer: "Интервью проходит в браузере на компьютере или телефоне с камерой и микрофоном." },
  { question: "Можно ли перезаписать ответ?", answer: "Если рекрутер разрешил перезапись, после ответа появятся кнопка «Перезаписать» и число оставшихся попыток." },
  { question: "Что делать, если пропала связь?", answer: "Открой ту же ссылку и продолжи с первого неотвеченного вопроса. Сохранённые ответы останутся. Прерванную запись может потребоваться повторить." },
  { question: "Кто принимает решение?", answer: "Рекрутер или нанимающий менеджер. ИИ готовит разбор ответов по критериям вакансии с цитатами. Внешность не оценивается." },
  { question: "Когда я получу результат?", answer: "Компания напишет на e-mail из приглашения. Если включена обратная связь, ты получишь разбор сильных сторон и зон роста. Сроки уточни у рекрутера." },
];
export function Faq() {
  return <section id="faq" className="landing-section faq-section" aria-labelledby="faq-title"><div className="faq-heading"><h2 id="faq-title">Остались <br />вопросы?</h2><Mascot name="think" /></div><Accordion className="faq-list">{FAQ_ITEMS.map(item => <Accordion.Item key={item.question} id={item.question} className="faq-item"><Accordion.Heading><Accordion.Trigger>{item.question}<Accordion.Indicator /></Accordion.Trigger></Accordion.Heading><Accordion.Panel><Accordion.Body><p>{item.answer}</p></Accordion.Body></Accordion.Panel></Accordion.Item>)}</Accordion></section>;
}
