"use client";

import Link from "@/lib/router";
import { usePathname } from "@/lib/router";
import { useEffect, useState } from "react";
import {
  BarChart3,
  Briefcase,
  Building2,
  Menu,
  PanelLeftClose,
  PanelLeftOpen,
  Plug,
  Users,
} from "lucide-react";

import { Logo } from "@/components/brand/logo";
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
  { href: "/dashboard", label: "Обзор", icon: BarChart3 },
  { href: "/vacancies", label: "Вакансии", icon: Briefcase },
  { href: "/candidates", label: "Кандидаты", icon: Users },
  { href: "/integrations", label: "Интеграции", icon: Plug },
  { href: "/organization", label: "Организация", icon: Building2 },
];

const SIDEBAR_STORAGE_KEY = "leonit.sidebar.collapsed";

function NavLinks({ collapsed, onNavigate }: { collapsed: boolean; onNavigate?: () => void }) {
  const pathname = usePathname();
  return (
    <nav className="sidebar-nav" aria-label="Основная навигация">
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
              "sidebar-nav-link",
              collapsed && "is-collapsed",
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
          "sidebar-brand",
          collapsed && "is-collapsed",
        )}
      >
        {onToggle ? (
          <Button
            variant="ghost"
            size="icon"
            onClick={onToggle}
            className="sidebar-toggle"
            aria-label={collapsed ? "Развернуть боковую панель" : "Свернуть боковую панель"}
            aria-expanded={!collapsed}
          >
            {collapsed ? <PanelLeftOpen className="h-4 w-4" /> : <PanelLeftClose className="h-4 w-4" />}
          </Button>
        ) : null}
        {!collapsed && <Link href="/dashboard" aria-label="LeonIT — на дашборд" onClick={onNavigate}><Logo size={26} /></Link>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <NavLinks collapsed={collapsed} onNavigate={onNavigate} />
      </div>
      <div className="sidebar-footer space-y-2">
        {footer}
      </div>
    </div>
  );
}

type SidebarFooter = React.ReactNode | ((collapsed: boolean, onNavigate?: () => void) => React.ReactNode);

function renderFooter(footer: SidebarFooter | undefined, collapsed: boolean, onNavigate?: () => void): React.ReactNode {
  return typeof footer === "function" ? footer(collapsed, onNavigate) : footer;
}

export function AppShell({
  children,
  header,
  sidebarFooter,
  assistant,
}: {
  children: React.ReactNode;
  header?: React.ReactNode;
  sidebarFooter?: SidebarFooter;
  assistant?: React.ReactNode;
}) {
  const isMobile = useIsMobile();
  const pathname = usePathname();
  const currentPage = NAV_ITEMS.find(item => pathname.startsWith(item.href));
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
    <div className="app-shell bg-background" data-sidebar-collapsed={collapsed}>
      {!isMobile && (
        <aside
          className="leon-sidebar hidden md:block"
        >
          <SidebarBody
            collapsed={collapsed}
            onToggle={toggle}
            footer={renderFooter(sidebarFooter, collapsed)}
          />
        </aside>
      )}

      <div
        className="workspace-main flex min-w-0 flex-1 flex-col"
      >
        <header className="workspace-topbar shrink-0">
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
                  footer={renderFooter(sidebarFooter, false, () => setMobileOpen(false))}
                />
              </SheetContent>
            </Sheet>
          )}
          <div className="workspace-breadcrumb"><strong>{currentPage?.label ?? "Кабинет"}</strong></div>
          <div className="flex min-w-0 flex-1 items-center gap-2">{header}</div>
        </header>
        <main className="min-h-0 flex-1 overflow-y-auto">
          <div className="workspace-content"><div key={pathname} className="workspace-page">{children}</div></div>
        </main>
      </div>
      {assistant}
    </div>
  );
}
