import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/page";

export const Route = createFileRoute("/")({
  head: () => ({ meta: [{ title: "Знакомьтесь с Leon · ИИ-интервью" }] }),
  component: Page,
});
