import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/legal/[slug]/page";

export const Route = createFileRoute("/legal/$slug")({
  head: () => ({ meta: [{ title: "Документы · Leon" }] }),
  component: Page,
});
