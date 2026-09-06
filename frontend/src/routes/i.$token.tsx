import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/i/[token]/page";

export const Route = createFileRoute("/i/$token")({
  head: () => ({ meta: [{ title: "Ваше интервью · Leon" }] }),
  component: Page,
});
