import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/integrations/huntflow/page";

export const Route = createFileRoute("/_app/integrations/huntflow")({
  head: () => ({ meta: [{ title: "Huntflow · Leon" }] }),
  component: Page,
});
