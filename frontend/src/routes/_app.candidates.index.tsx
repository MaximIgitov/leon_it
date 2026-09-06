import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/candidates/page";

export const Route = createFileRoute("/_app/candidates/")({
  head: () => ({ meta: [{ title: "Кандидаты · Leon" }] }),
  component: Page,
});
