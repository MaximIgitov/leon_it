import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/vacancies/[id]/page";

export const Route = createFileRoute("/_app/vacancies/$id/")({
  head: () => ({ meta: [{ title: "Вакансия · Leon" }] }),
  component: Page,
});
