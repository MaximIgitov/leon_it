"use client";

import { createContext, useContext, useEffect, useState, type ReactNode } from "react";

type Theme = "light" | "dark" | "system";
const STORAGE_KEY = "leonit.theme";
const ThemeContext = createContext<{ isDark: boolean; setTheme: (theme: Theme) => void }>({ isDark: false, setTheme: () => {} });
const validTheme = (value: unknown): Theme => value === "light" || value === "dark" ? value : "system";

// Runs before the first paint, including when a saved choice differs from the OS.
export const themeInitScript = `(function(){var t='system';try{t=localStorage.getItem('${STORAGE_KEY}')||t}catch{}var d=t==='dark'||(t!=='light'&&matchMedia('(prefers-color-scheme: dark)').matches);document.documentElement.classList.toggle('dark',d);document.documentElement.dataset.theme=d?'dark':'light';})()`;

export function ThemeProvider({ children }: { children: ReactNode }) {
  const [theme, setPreference] = useState<Theme | null>(null);
  const [isDark, setIsDark] = useState(false);

  useEffect(() => {
    try { setPreference(validTheme(localStorage.getItem(STORAGE_KEY))); }
    catch { setPreference("system"); }
    const sync = (event: StorageEvent) => {
      if (event.key === STORAGE_KEY || event.key === null) setPreference(validTheme(event.newValue));
    };
    window.addEventListener("storage", sync);
    return () => window.removeEventListener("storage", sync);
  }, []);

  useEffect(() => {
    if (theme === null) return;
    const media = matchMedia("(prefers-color-scheme: dark)");
    const apply = () => {
      const dark = theme === "dark" || (theme === "system" && media.matches);
      setIsDark(dark);
      document.documentElement.classList.toggle("dark", dark);
      document.documentElement.dataset.theme = dark ? "dark" : "light";
      document.querySelector('meta[name="theme-color"]')?.setAttribute("content", dark ? "#171b19" : "#ffffff");
    };
    apply();
    media.addEventListener("change", apply);
    return () => media.removeEventListener("change", apply);
  }, [theme]);

  const setTheme = (next: Theme) => {
    setPreference(next);
    try { localStorage.setItem(STORAGE_KEY, next); } catch { /* Keep the choice for this visit. */ }
  };

  return <ThemeContext.Provider value={{ isDark, setTheme }}>{children}</ThemeContext.Provider>;
}

export const useTheme = () => useContext(ThemeContext);
