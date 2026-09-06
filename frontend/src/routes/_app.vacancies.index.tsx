import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/vacancies/page";

export const Route = createFileRoute("/_app/vacancies/")({
  head: () => ({ meta: [{ title: "Вакансии · Leon" }] }),
  component: Page,
});
