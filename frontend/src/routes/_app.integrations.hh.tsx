import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/integrations/hh/page";

export const Route = createFileRoute("/_app/integrations/hh")({
  head: () => ({ meta: [{ title: "HeadHunter · Leon" }] }),
  component: Page,
});
