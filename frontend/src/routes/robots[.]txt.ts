import { createFileRoute } from "@tanstack/react-router";
import robots from "@/app/robots";

export const Route = createFileRoute("/robots.txt")({
  server: {
    handlers: {
      GET: () => {
        const { rules, sitemap } = robots();
        return new Response([
          ...rules.flatMap((rule) => [`User-agent: ${rule.userAgent}`, `Allow: ${rule.allow}`, ...rule.disallow.map((path) => `Disallow: ${path}`)]),
          `Sitemap: ${sitemap}`,
        ].join("\n"), { headers: { "Content-Type": "text/plain; charset=utf-8" } });
      },
    },
  },
});
