import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/r/[token]/page";

export const Route = createFileRoute("/r/$token")({
  head: () => ({ meta: [{ title: "Результат интервью · Leon" }] }),
  component: Page,
});
