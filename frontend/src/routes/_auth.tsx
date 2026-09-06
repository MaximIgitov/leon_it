import { Outlet, createFileRoute } from "@tanstack/react-router";
import Layout from "@/app/(auth)/layout";

export const Route = createFileRoute("/_auth")({
  component: () => <Layout><Outlet /></Layout>,
});
