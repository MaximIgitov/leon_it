"use client";

import { useParams, useSearchParams } from "@/lib/router";
import { useCallback, useEffect, useState } from "react";
import { Check, ChevronRight, FileText, Pencil, Settings2, Sparkles } from "lucide-react";

import { DATA_CHANGED_EVENT } from "@/components/assistant/assistant-panel";
import { openAssistant } from "@/components/assistant/dock";
import { useAuth } from "@/components/auth/auth-provider";
import { PageHeader } from "@/components/layout/page-header";
import { InterviewsTable } from "@/components/candidates/interviews-table";
import { InviteDialog } from "@/components/candidates/invite-dialog";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { RankingTable } from "@/components/reports/ranking-table";
import { QuestionsEditor } from "@/components/vacancies/questions-editor";
import { RubricEditor } from "@/components/vacancies/rubric-editor";
import { SettingsEditor } from "@/components/vacancies/settings-editor";
import { VacancyDescriptionEditor, VacancyStatusActions } from "@/components/vacancies/vacancy-editors";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PageSkeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api/client";
import { LEVEL_LABELS, VACANCY_STATUS_LABELS, vacanciesApi, type Vacancy } from "@/lib/api/vacancies";

const TABS = new Set(["description", "rubric", "questions", "settings", "candidates", "ranking", "metrics"]);

export default function VacancyPage() {
  const params = useParams<{ id: string }>();
  const searchParams = useSearchParams();
  const { can } = useAuth();
  const { toast } = useToast();
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("description");
  const [interviewRevision, setInterviewRevision] = useState(0);
  const [editor, setEditor] = useState<"description" | "settings" | "rubric" | null>(null);

  useEffect(() => {
    // Ссылки из ассистента ведут на конкретную вкладку: /vacancies/<id>?tab=questions.
    const wanted = searchParams.get("tab");
    if (wanted === "settings" || wanted === "rubric") setEditor(wanted);
    else setTab(wanted && TABS.has(wanted) ? wanted : "description");
  }, [searchParams]);

  const load = useCallback(async () => {
    try {
      setVacancy(await vacanciesApi.get(params.id));
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.message : "Не удалось загрузить вакансию");
    }
  }, [params.id]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    // Ассистент применил рубрику, вопросы или публикацию — показываем без перезагрузки.
    const handler = () => void load();
    window.addEventListener(DATA_CHANGED_EVENT, handler);
    return () => window.removeEventListener(DATA_CHANGED_EVENT, handler);
  }, [load]);

  useEffect(() => {
    // Черновик собран из текста: напомнить, что рубрику и вопросы стоит проверить.
    if (typeof window === "undefined") return;
    const params = new URLSearchParams(window.location.search);
    if (params.get("from") !== "text") return;
    toast({
      title: "Черновик собран из текста",
      description:
        "Проверьте описание, рубрику и вопросы: модель могла что-то упустить или додумать.",
    });
    window.history.replaceState(null, "", window.location.pathname);
  }, [toast]);

  const notifyError = useCallback(
    (caught: unknown, fallback: string) =>
      toast({
        variant: "destructive",
        title: caught instanceof ApiError ? caught.message : fallback,
      }),
    [toast],
  );

  if (error) {
    return (
      <>
        <PageHeader title="Вакансия" />
        <p className="text-destructive">{error}</p>
      </>
    );
  }
  if (!vacancy) return <PageSkeleton />;

  const editable = can("vacancy.write") && vacancy.status !== "archived";

  const readiness = [
    { label: "Описание", done: Boolean(vacancy.description.trim()), action: () => setEditor("description") },
    { label: "Критерии оценки", done: vacancy.rubric.length > 0, action: () => setEditor("rubric") },
    { label: "Вопросы", done: vacancy.questions.length > 0, action: () => setTab("questions") },
  ];
  const completed = readiness.filter((step) => step.done).length;

  return (
    <>
      <PageHeader title={vacancy.title} actions={<div className="flex flex-wrap items-center gap-3">
        {can("candidate.write") && vacancy.status === "published" && <InviteDialog vacancyId={vacancy.id} onInvited={() => { setInterviewRevision(value => value + 1); setTab("candidates"); }} />}
        {can("vacancy.write") && <VacancyStatusActions vacancy={vacancy} onChange={setVacancy} onError={notifyError} />}
      </div>} />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-5">
          <TabsTrigger value="description">Обзор</TabsTrigger>
          <TabsTrigger value="questions">Вопросы</TabsTrigger>
          <TabsTrigger value="candidates">Кандидаты</TabsTrigger>
          <TabsTrigger value="ranking">Рейтинг</TabsTrigger>
          <TabsTrigger value="metrics">Статистика</TabsTrigger>
        </TabsList>
        <TabsContent value="description">
          <div className="vacancy-layout">
            <article className="vacancy-description">
              <div className="flex items-center justify-between gap-3 mb-6"><h2>О вакансии</h2>{editable && <Button variant="ghost" size="icon" aria-label="Редактировать описание" onClick={() => setEditor("description")}><Pencil size={18} /></Button>}</div>
              <p className="whitespace-pre-wrap">{vacancy.description || "Добавьте описание вакансии."}</p>
              {vacancy.requirements && <><h3>Что важно</h3><p className="whitespace-pre-wrap">{vacancy.requirements}</p></>}
              {vacancy.skills.length > 0 && <><h3>Навыки</h3><div className="vacancy-skills">{vacancy.skills.map((skill) => <span key={skill}>{skill}</span>)}</div></>}
            </article>
            <aside className="vacancy-properties">
              <section>
                <h2>Детали</h2>
                <dl><div><dt>Статус</dt><dd><i className={`status-dot status-${vacancy.status}`} />{VACANCY_STATUS_LABELS[vacancy.status]}</dd></div><div><dt>Уровень</dt><dd>{vacancy.level ? LEVEL_LABELS[vacancy.level] : "Не указан"}</dd></div><div><dt>Вопросы</dt><dd>{vacancy.questions.length}</dd></div><div><dt>Обновлена</dt><dd>{new Date(vacancy.updated_at).toLocaleDateString("ru-RU")}</dd></div></dl>
                <Button variant="ghost" className="vacancy-settings-link w-full justify-start" onClick={() => setEditor("settings")}><Settings2 size={17} /><span>Настройки интервью</span><ChevronRight size={16} className="ml-auto" /></Button>
              </section>
              <section className="vacancy-readiness">
                <div className="readiness-heading"><div><h2>Готовность вакансии</h2><p>{completed === 3 ? "Всё готово к знакомству" : "Подготовьте три раздела"}</p></div><Sparkles size={28} aria-hidden /></div>
                <div className="readiness-count"><strong>{completed}<span> / 3</span></strong><span>{completed === 3 ? "Можно публиковать" : "раздела готовы"}</span></div>
                <progress value={completed} max={3} aria-label="Готовность вакансии" />
                {readiness.map((step) => <button key={step.label} onClick={step.action}><span className={step.done ? "step-done" : "step-todo"}>{step.done ? <Check size={17} strokeWidth={3} /> : <FileText size={17} />}</span>{step.label}<ChevronRight size={14} className="ml-auto" /></button>)}
              </section>
              {editable && <Button variant="outline" className="w-full" onClick={() => openAssistant({ prompt: `Помоги с вакансией «${vacancy.title}»: проверь описание, критерии и вопросы интервью.` })}><Sparkles size={17} />Помощь Леона</Button>}
            </aside>
          </div>
        </TabsContent>
        <TabsContent value="questions"><QuestionsEditor vacancy={vacancy} editable={editable} onSaved={setVacancy} onError={notifyError} /><Button variant="ghost" className="mt-3" onClick={() => setEditor("rubric")}>Критерии оценки · {vacancy.rubric.length}<ChevronRight size={16} /></Button></TabsContent>
        <TabsContent value="candidates">{vacancy.status === "published" ? <InterviewsTable key={interviewRevision} vacancyId={vacancy.id} showInvite={false} /> : <p className="rounded-2xl border border-dashed p-8 text-muted-foreground">Приглашения станут доступны после публикации.</p>}</TabsContent>
        <TabsContent value="ranking"><RankingTable vacancyId={vacancy.id} /></TabsContent>
        <TabsContent value="metrics"><DashboardPanel vacancyId={vacancy.id} /></TabsContent>
      </Tabs>
      <Dialog open={editor !== null} onOpenChange={(open) => { if (!open) setEditor(null); }}>
        <DialogContent className="vacancy-editor-dialog flex flex-col overflow-hidden sm:max-w-[760px] [&_.leon-card-header]:hidden [&_.leon-card-content]:p-0 [&_.leon-card]:border-0">
          <DialogHeader><DialogTitle>{editor === "description" ? "Описание вакансии" : editor === "rubric" ? "Критерии оценки" : "Настройки интервью"}</DialogTitle></DialogHeader>
          <div className="vacancy-editor-body min-h-0 overflow-y-auto">
          {editor === "description" && <VacancyDescriptionEditor vacancy={vacancy} editable={editable} onSaved={(updated) => { setVacancy(updated); setEditor(null); }} onError={notifyError} />}
          {editor === "rubric" && <RubricEditor vacancy={vacancy} editable={editable} onSaved={setVacancy} onError={notifyError} />}
          {editor === "settings" && <SettingsEditor vacancy={vacancy} editable={editable} onSaved={setVacancy} onError={notifyError} />}
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
