"use client";

import { useEffect, useState } from "react";

import { useAuth } from "@/components/auth/auth-provider";
import { DashboardPanel } from "@/components/dashboard/dashboard-panel";
import { PageHeader } from "@/components/layout/page-header";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { VACANCY_STATUS_LABELS, vacanciesApi, type VacancyListItem } from "@/lib/api/vacancies";

// Отдельное значение для обзора всех вакансий.
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

      <DashboardPanel
        vacancyId={vacancyId === ALL ? null : vacancyId}
        toolbar={
          <Select value={vacancyId} onValueChange={setVacancyId}>
            <SelectTrigger className="w-full max-w-64" aria-label="Вакансия">
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
