import { HeadContent, Link, Outlet, Scripts, createRootRoute } from "@tanstack/react-router";
import "@fontsource-variable/nunito";
import "@fontsource-variable/jetbrains-mono";
import "@/app/globals.css";

import { Providers } from "@/components/providers";
import { themeInitScript } from "@/components/theme-provider";
import { ThemeSwitch } from "@/components/ui/theme-switch";
import { Toaster } from "@/components/ui/toaster";
import { SITE_URL } from "@/lib/site";

export const Route = createRootRoute({
  head: () => ({
    meta: [
      { charSet: "utf-8" },
      { name: "viewport", content: "width=device-width, initial-scale=1, viewport-fit=cover" },
      { title: "Leon · ИИ-интервью" },
      { name: "description", content: "ИИ-собеседования в удобное время. Знакомьтесь, отвечайте и находите свою команду." },
      { name: "theme-color", content: "#ffffff" },
      { property: "og:type", content: "website" },
      { property: "og:locale", content: "ru_RU" },
      { property: "og:site_name", content: "Leon" },
      { property: "og:title", content: "Leon · ИИ-интервью" },
      { property: "og:description", content: "Знакомьтесь, отвечайте и находите свою команду. ИИ-собеседования в удобное время." },
      { property: "og:url", content: SITE_URL },
    ],
    links: [{ rel: "icon", type: "image/png", href: "/brand/logo.png" }],
  }),
  component: RootLayout,
  notFoundComponent: () => (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 p-6 text-center">
      <ThemeSwitch /><p className="text-sm font-bold text-muted-foreground">404</p>
      <h1 className="text-3xl font-extrabold">Страница не найдена</h1>
      <Link to="/" className="font-bold text-primary underline underline-offset-4">На главную</Link>
    </main>
  ),
});

function RootLayout() {
  return (
    <html lang="ru" suppressHydrationWarning>
      <head><script dangerouslySetInnerHTML={{ __html: themeInitScript }} /><HeadContent /></head>
      <body>
        <Providers>
          <Outlet />
          <Toaster />
        </Providers>
        <Scripts />
      </body>
    </html>
  );
}
