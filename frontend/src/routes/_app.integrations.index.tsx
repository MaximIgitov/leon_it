import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/integrations/page";

export const Route = createFileRoute("/_app/integrations/")({
  head: () => ({ meta: [{ title: "Интеграции · Leon" }] }),
  component: Page,
});
