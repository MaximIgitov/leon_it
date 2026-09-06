"use client";

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { Loader2, Sparkles } from "lucide-react";

import { DATA_CHANGED_EVENT } from "@/components/assistant/assistant-panel";
import { openAssistant } from "@/components/assistant/dock";
import { useAuth } from "@/components/auth/auth-provider";
import { PageHeader } from "@/components/layout/page-header";
import { InterviewsTable } from "@/components/candidates/interviews-table";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { RankingTable } from "@/components/reports/ranking-table";
import { QuestionsEditor } from "@/components/vacancies/questions-editor";
import { RubricEditor } from "@/components/vacancies/rubric-editor";
import { SettingsEditor } from "@/components/vacancies/settings-editor";
import { VacancyDescriptionEditor, VacancyStatusActions } from "@/components/vacancies/vacancy-editors";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useToast } from "@/hooks/use-toast";
import { ApiError } from "@/lib/api/client";
import { VACANCY_STATUS_LABELS, vacanciesApi, type Vacancy } from "@/lib/api/vacancies";

const TABS = new Set(["description", "rubric", "questions", "settings", "candidates", "ranking", "metrics"]);

export default function VacancyPage() {
  const params = useParams<{ id: string }>();
  const { can } = useAuth();
  const { toast } = useToast();
  const [vacancy, setVacancy] = useState<Vacancy | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tab, setTab] = useState("description");

  useEffect(() => {
    // Ссылки из ассистента ведут на конкретную вкладку: /vacancies/<id>?tab=questions.
    if (typeof window === "undefined") return;
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (wanted && TABS.has(wanted)) setTab(wanted);
  }, []);

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
  if (!vacancy) return <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />;

  const editable = can("vacancy.write") && vacancy.status !== "archived";

  return (
    <>
      <PageHeader
        title={vacancy.title}
        description={`${vacancy.question_count} вопр. · обновлена ${new Date(vacancy.updated_at).toLocaleDateString("ru-RU")}`}
        actions={
          <div className="flex items-center gap-2">
            <Badge variant={vacancy.status === "published" ? "default" : "secondary"}>
              {VACANCY_STATUS_LABELS[vacancy.status]}
            </Badge>
            {editable ? (
              <Button
                variant="outline"
                size="sm"
                onClick={() =>
                  openAssistant({
                    prompt: `Помоги с вакансией «${vacancy.title}»: проверь описание, составь рубрику компетенций и вопросы интервью.`,
                  })
                }
              >
                <Sparkles className="mr-2 h-4 w-4 text-primary" />
                Собрать с ИИ
              </Button>
            ) : null}
            {can("vacancy.write") ? (
              <VacancyStatusActions vacancy={vacancy} onChange={setVacancy} onError={notifyError} />
            ) : null}
          </div>
        }
      />
      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-4 flex-wrap">
          <TabsTrigger value="description">Описание</TabsTrigger>
          <TabsTrigger value="rubric">Рубрика ({vacancy.rubric.length})</TabsTrigger>
          <TabsTrigger value="questions">Вопросы ({vacancy.questions.length})</TabsTrigger>
          <TabsTrigger value="settings">Настройки интервью</TabsTrigger>
          <TabsTrigger value="candidates">Кандидаты</TabsTrigger>
          <TabsTrigger value="ranking">Рейтинг</TabsTrigger>
          <TabsTrigger value="metrics">Метрики</TabsTrigger>
        </TabsList>
        <TabsContent value="metrics">
          <DashboardPanel vacancyId={vacancy.id} />
        </TabsContent>
        <TabsContent value="ranking">
          <RankingTable vacancyId={vacancy.id} />
        </TabsContent>
        <TabsContent value="candidates">
          {vacancy.status === "published" ? (
            <InterviewsTable vacancyId={vacancy.id} />
          ) : (
            <p className="rounded-lg border border-dashed p-6 text-sm text-muted-foreground">
              Приглашать кандидатов можно после публикации вакансии.
            </p>
          )}
        </TabsContent>
        <TabsContent value="description">
          <VacancyDescriptionEditor
            vacancy={vacancy}
            editable={editable}
            onSaved={setVacancy}
            onError={notifyError}
          />
        </TabsContent>
        <TabsContent value="rubric">
          <RubricEditor vacancy={vacancy} editable={editable} onSaved={setVacancy} onError={notifyError} />
        </TabsContent>
        <TabsContent value="questions">
          <QuestionsEditor vacancy={vacancy} editable={editable} onSaved={setVacancy} onError={notifyError} />
        </TabsContent>
        <TabsContent value="settings">
          <SettingsEditor vacancy={vacancy} editable={editable} onSaved={setVacancy} onError={notifyError} />
        </TabsContent>
      </Tabs>
    </>
  );
}
