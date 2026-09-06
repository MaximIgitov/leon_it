import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/unsubscribe/[token]/page";

export const Route = createFileRoute("/unsubscribe/$token")({
  head: () => ({ meta: [{ title: "Управление рассылкой · Leon" }] }),
  component: Page,
});
