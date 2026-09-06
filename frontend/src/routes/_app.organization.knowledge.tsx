import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/organization/knowledge/page";

export const Route = createFileRoute("/_app/organization/knowledge")({
  head: () => ({ meta: [{ title: "База знаний · Leon" }] }),
  component: Page,
});
