import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/vacancies/[id]/interviews/[interviewId]/page";

export const Route = createFileRoute("/_app/vacancies/$id/interviews/$interviewId")({
  head: () => ({ meta: [{ title: "Собеседование · Leon" }] }),
  component: Page,
});
