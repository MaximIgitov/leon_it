import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(auth)/login/page";

export const Route = createFileRoute("/_auth/login")({
  head: () => ({ meta: [{ title: "Вход · Leon" }] }),
  component: Page,
});
