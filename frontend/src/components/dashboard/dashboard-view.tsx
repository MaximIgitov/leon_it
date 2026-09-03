"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { PageHeader } from "@/components/layout/page-header";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { VACANCY_STATUS_LABELS, vacanciesApi, type VacancyListItem } from "@/lib/api/vacancies";

// Radix Select не принимает пустое значение — «все вакансии» кодируем словом.
const ALL = "all";

export function DashboardView() {
  const { can } = useAuth();
  const [vacancies, setVacancies] = useState<VacancyListItem[]>([]);
  const [vacancyId, setVacancyId] = useState<string>(ALL);

  useEffect(() => {
    vacanciesApi
      .list()
      .then(setVacancies)
      .catch(() => setVacancies([]));
  }, []);

  if (!can("dashboard.read")) {
    return (
      <>
        <PageHeader title="Дашборд" />
        <p className="text-muted-foreground">Метрики недоступны для вашей роли.</p>
      </>
    );
  }

  return (
    <>
      <PageHeader
        title="Дашборд"
        description="Воронка кандидатов, сроки, баллы и согласие решений с рекомендацией ИИ."
      />
      <DashboardPanel
        vacancyId={vacancyId === ALL ? null : vacancyId}
        toolbar={
          <Select value={vacancyId} onValueChange={setVacancyId}>
            <SelectTrigger className="w-full sm:w-72" aria-label="Вакансия">
              <SelectValue placeholder="Все вакансии" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL}>Все вакансии</SelectItem>
              {vacancies.map((vacancy) => (
                <SelectItem key={vacancy.id} value={vacancy.id}>
                  {vacancy.title}
                  {vacancy.status !== "published" ? (
                    <span className="ml-1.5 text-xs text-muted-foreground">
                      · {VACANCY_STATUS_LABELS[vacancy.status].toLowerCase()}
                    </span>
                  ) : null}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        }
      />
    </>
  );
}
