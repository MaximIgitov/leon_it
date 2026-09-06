import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/practice/page";

export const Route = createFileRoute("/practice")({
  head: () => ({ meta: [{ title: "Пробное интервью · Leon" }] }),
  component: Page,
});
