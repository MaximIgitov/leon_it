import { Outlet, createFileRoute } from "@tanstack/react-router";
import Layout from "@/app/(app)/layout";

export const Route = createFileRoute("/_app")({
  component: () => <Layout><Outlet /></Layout>,
});
