"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Briefcase,
  Building2,
  Menu,
  Monitor,
  Moon,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Sun,
  Users,
} from "lucide-react";
import { useTheme } from "next-themes";

import { Logo, LogoMark } from "@/components/brand/logo";
import { Button } from "@/components/ui/button";
import { Sheet, SheetContent, SheetTitle, SheetTrigger } from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-is-mobile";
import { cn } from "@/lib/utils";

export type NavItem = {
  href: string;
  label: string;
  icon: React.ElementType;
};

export const NAV_ITEMS: NavItem[] = [
  { href: "/dashboard", label: "Дашборд", icon: BarChart3 },
  { href: "/vacancies", label: "Вакансии", icon: Briefcase },
  { href: "/candidates", label: "Кандидаты", icon: Users },
  { href: "/integrations", label: "Интеграции", icon: Plug },
  { href: "/organization", label: "Организация", icon: Building2 },
];

const SIDEBAR_STORAGE_KEY = "leonit.sidebar.collapsed";

function ThemeToggle({ compact }: { compact: boolean }) {
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  if (!mounted) return null;

  const options = [
    { value: "light", icon: Sun, label: "Светлая" },
    { value: "dark", icon: Moon, label: "Тёмная" },
    { value: "system", icon: Monitor, label: "Системная" },
  ] as const;

  return (
    <div
      className={cn(
        "flex items-center gap-1 rounded-lg bg-muted p-1",
        compact ? "flex-col" : "justify-between",
      )}
      role="radiogroup"
      aria-label="Тема оформления"
    >
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="radio"
          aria-checked={theme === option.value}
          aria-label={option.label}
          title={option.label}
          onClick={() => setTheme(option.value)}
          className={cn(
            "rounded-md p-1.5 transition-colors",
            theme === option.value
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          <option.icon className="h-4 w-4" />
        </button>
      ))}
    </div>
  );
}

function NavLinks({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="flex flex-1 flex-col gap-1 px-2" aria-label="Основная навигация">
      {NAV_ITEMS.map((item) => {
        const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
        return (
          <Link
            key={item.href}
            href={item.href}
            onClick={onNavigate}
            title={collapsed ? item.label : undefined}
            aria-current={active ? "page" : undefined}
            className={cn(
              "flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition-colors",
              active
                ? "bg-primary/10 text-primary"
                : "text-muted-foreground hover:bg-muted hover:text-foreground",
              collapsed && "justify-center px-2",
            )}
          >
            <item.icon className="h-4 w-4 shrink-0" />
            {!collapsed && <span className="truncate">{item.label}</span>}
          </Link>
        );
      })}
    </nav>
  );
}

function SidebarBody({
  collapsed,
  onToggle,
  onNavigate,
  footer,
}: {
  collapsed: boolean;
  onToggle?: () => void;
  onNavigate?: () => void;
  footer?: React.ReactNode;
}) {
  return (
    <div className="flex h-full flex-col">
      <div
        className={cn(
          "flex h-16 items-center border-b px-3",
          collapsed ? "justify-center" : "justify-between",
        )}
      >
        <Link href="/dashboard" aria-label="LeonIT — на дашборд" onClick={onNavigate}>
          {collapsed ? <LogoMark size={28} /> : <Logo size={28} />}
        </Link>
        {onToggle && !collapsed ? (
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggle}
            aria-label="Свернуть боковую панель"
          >
            <PanelLeftClose className="h-4 w-4" />
          </Button>
        ) : null}
      </div>
      <div className="flex-1 overflow-y-auto py-3">
        <NavLinks collapsed={collapsed} onNavigate={onNavigate} />
      </div>
      <div className="space-y-2 border-t p-3">
        {onToggle && collapsed ? (
          <Button
            variant="ghost"
            size="icon"
            className="w-full"
            onClick={onToggle}
            aria-label="Развернуть боковую панель"
          >
            <PanelLeftOpen className="h-4 w-4" />
          </Button>
        ) : null}
        <ThemeToggle compact={collapsed} />
        {footer}
      </div>
    </div>
  );
}

type SidebarFooter = React.ReactNode | ((collapsed: boolean) => React.ReactNode);

function renderFooter(footer: SidebarFooter | undefined, collapsed: boolean): React.ReactNode {
  return typeof footer === "function" ? footer(collapsed) : footer;
}

export function AppShell({
  children,
  header,
  sidebarFooter,
}: {
  children: React.ReactNode;
  header?: React.ReactNode;
  sidebarFooter?: SidebarFooter;
}) {
  const isMobile = useIsMobile();
  const [collapsed, setCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  useEffect(() => {
    try {
      setCollapsed(window.localStorage.getItem(SIDEBAR_STORAGE_KEY) === "1");
    } catch {
      /* приватный режим — оставляем значение по умолчанию */
    }
  }, []);

  const toggle = () => {
    setCollapsed((value) => {
      const next = !value;
      try {
        window.localStorage.setItem(SIDEBAR_STORAGE_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  };

  return (
    <div className="app-shell flex bg-background">
      {!isMobile && (
        <aside
          className={cn(
            "hidden shrink-0 border-r bg-card transition-[width] duration-200 md:block",
            collapsed ? "w-16" : "w-60",
          )}
        >
          <SidebarBody
            collapsed={collapsed}
            onToggle={toggle}
            footer={renderFooter(sidebarFooter, collapsed)}
          />
        </aside>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-3 sm:px-4">
          {isMobile && (
            <Sheet open={mobileOpen} onOpenChange={setMobileOpen}>
              <SheetTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="Открыть меню">
                  <Menu className="h-5 w-5" />
                </Button>
              </SheetTrigger>
              <SheetContent side="left" className="w-72 p-0">
                <SheetTitle className="sr-only">Навигация</SheetTitle>
                <SidebarBody
                  collapsed={false}
                  onNavigate={() => setMobileOpen(false)}
                  footer={renderFooter(sidebarFooter, false)}
                />
              </SheetContent>
            </Sheet>
          )}
          <div className="flex min-w-0 flex-1 items-center gap-2">{header}</div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="mx-auto w-full max-w-6xl p-4 sm:p-6">{children}</div>
        </main>
      </div>
    </div>
  );
}
