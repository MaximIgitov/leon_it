import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/dashboard/page";

export const Route = createFileRoute("/_app/dashboard")({
  head: () => ({ meta: [{ title: "Обзор · Leon" }] }),
  component: Page,
});
