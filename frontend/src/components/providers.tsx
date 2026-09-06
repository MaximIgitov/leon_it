import { I18nProvider } from "@react-aria/i18n";
import { AuthProvider } from "@/components/auth/auth-provider";
import { ThemeProvider } from "@/components/theme-provider";

export function Providers({ children }: { children: React.ReactNode }) {
  return <I18nProvider locale="ru-RU"><ThemeProvider><AuthProvider>{children}</AuthProvider></ThemeProvider></I18nProvider>;
}
