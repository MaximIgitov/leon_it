import { AppShell } from "@/components/layout/app-shell";

// Авторизация и данные пользователя подключаются в PR 4; оболочка кабинета
// (боковая панель, шапка, тема) уже здесь, чтобы страницы разделов строились
// на готовом каркасе.
export default function AppLayout({ children }: { children: React.ReactNode }) {
  return <AppShell>{children}</AppShell>;
}
