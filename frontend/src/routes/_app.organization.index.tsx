import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/organization/page";

export const Route = createFileRoute("/_app/organization/")({
  head: () => ({ meta: [{ title: "Команда · Leon" }] }),
  component: Page,
});
