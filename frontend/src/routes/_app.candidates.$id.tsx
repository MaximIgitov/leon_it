import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(app)/candidates/[id]/page";

export const Route = createFileRoute("/_app/candidates/$id")({
  head: () => ({ meta: [{ title: "Кандидат · Leon" }] }),
  component: Page,
});
