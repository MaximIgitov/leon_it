import type { Metadata, Viewport } from "next";
import "@fontsource-variable/manrope";
import "@fontsource-variable/jetbrains-mono";
import "./globals.css";

import { Providers } from "@/components/providers";
import { Toaster } from "@/components/ui/toaster";

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: "#140AF0",
};

const siteUrl = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

export const metadata: Metadata = {
  metadataBase: new URL(siteUrl),
  title: {
    default: "LeonIT — ИИ-интервьюер",
    template: "%s | LeonIT",
  },
  description:
    "Асинхронное техническое видеоинтервью с ИИ-оценкой: кандидат отвечает на вопросы в удобное время, рекрутер и нанимающий менеджер получают структурированное заключение.",
  openGraph: {
    type: "website",
    locale: "ru_RU",
    siteName: "LeonIT",
    title: "LeonIT — ИИ-интервьюер",
    description:
      "Пройдите техническое интервью онлайн в удобное время — без согласования слотов с экспертом.",
    url: siteUrl,
  },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru" suppressHydrationWarning>
      <body>
        <Providers>
          {children}
          <Toaster />
        </Providers>
      </body>
    </html>
  );
}
