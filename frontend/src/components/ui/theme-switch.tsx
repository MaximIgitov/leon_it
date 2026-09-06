"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "@/components/theme-provider";

export function ThemeSwitch() {
  const { isDark, setTheme } = useTheme();
  return <button type="button" role="switch" aria-label="Тёмная тема" aria-checked={isDark}
    title={isDark ? "Включить светлую тему" : "Включить тёмную тему"}
    className="theme-switch" onClick={() => setTheme(isDark ? "light" : "dark")}>
    <span className="theme-switch-track" aria-hidden="true"><span className="theme-switch-thumb" /><Sun className="theme-switch-sun" size={17} strokeWidth={2.3} /><Moon className="theme-switch-moon" size={16} strokeWidth={2.3} /></span>
  </button>;
}
