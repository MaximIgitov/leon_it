import Link from "@/lib/router";
import { ArrowRight, AudioLines, Check, Quote } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function ForRecruiters() {
  return <section id="recruiters" className="landing-section" aria-labelledby="recruiters-title">
    <div className="recruiter-report-section">
      <div className="recruiter-copy">
        <h2 id="recruiters-title">Отчёт по каждому интервью</h2>
        <p>Посмотрите ответы, сравните навыки и обсудите кандидата с командой.</p>
        <Button size="lg" asChild><Link href="/register">Создать вакансию <ArrowRight size={19} /></Link></Button>
      </div>
      <div className="report-sample" aria-label="Пример отчёта об интервью">
        <div className="report-sample-header"><strong>Frontend-разработчик</strong><span>Пример отчёта</span></div>
        <Tabs defaultValue="answers">
          <TabsList aria-label="Содержание примера отчёта"><TabsTrigger value="answers">Ответы</TabsTrigger><TabsTrigger value="skills">Критерии</TabsTrigger><TabsTrigger value="quotes">Цитаты</TabsTrigger></TabsList>
          <TabsContent value="answers"><ol className="report-sample-answers">{["Расскажи о своём проекте", "Как ты выбирал решение?", "Как работал с командой?"].map((question, index) => <li key={question}><span>0{index + 1}</span><strong>{question}</strong><AudioLines size={22} aria-hidden /></li>)}</ol></TabsContent>
          <TabsContent value="skills"><div className="report-sample-skills">{["Технические навыки", "Решение задач", "Работа в команде"].map(skill => <div key={skill}><Check size={22} aria-hidden /><strong>{skill}</strong></div>)}<p>Вы задаёте критерии в вакансии. Леон разбирает ответы по каждому из них.</p></div></TabsContent>
          <TabsContent value="quotes"><blockquote className="report-sample-quote"><Quote size={30} aria-hidden /><p>«Я отвечал за интерфейс: обсудил сценарии с дизайнером и разбил работу на небольшие задачи».</p><footer>Пример цитаты из ответа</footer></blockquote></TabsContent>
        </Tabs>
      </div>
    </div>
  </section>;
}
