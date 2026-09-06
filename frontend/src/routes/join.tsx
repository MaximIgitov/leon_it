import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/join/page";

export const Route = createFileRoute("/join")({
  head: () => ({ meta: [{ title: "Приглашение в команду · Leon" }] }),
  component: Page,
});
