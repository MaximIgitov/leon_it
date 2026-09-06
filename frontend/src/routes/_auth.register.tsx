import { createFileRoute } from "@tanstack/react-router";
import Page from "@/app/(auth)/register/page";

export const Route = createFileRoute("/_auth/register")({
  head: () => ({ meta: [{ title: "Регистрация · Leon" }] }),
  component: Page,
});
