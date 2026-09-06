import { createRouter } from "@tanstack/react-router";
import type {} from "@tanstack/react-start";
import { routeTree } from "./routeTree.gen";

export function getRouter() {
  return createRouter({
    routeTree,
    defaultPreload: "intent",
    defaultViewTransition: {
      types: ({ pathChanged }) => pathChanged ? ["route"] : false,
    },
    scrollRestoration: true,
  });
}

declare module "@tanstack/react-router" {
  interface Register {
    router: ReturnType<typeof getRouter>;
  }
}
