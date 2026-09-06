"use client";

import { AssistantPanel } from "@/components/assistant/assistant-panel";
import { ASSISTANT_DOCK_WIDTH, AssistantDockProvider, useAssistantDock } from "@/components/assistant/dock";
import { RequireAuth } from "@/components/auth/auth-provider";
import { AppShell } from "@/components/layout/app-shell";
import { UserMenu } from "@/components/layout/user-menu";
import { useIsMobile } from "@/hooks/use-is-mobile";

function Shell({ children }: { children: React.ReactNode }) {
  const { open } = useAssistantDock();
  // На узких экранах панель раскрывается поверх страницы, сдвигать нечего.
  const isMobile = useIsMobile(1024);
  return (
    <AppShell
      header={
        <div className="ml-auto flex items-center gap-2">
          <AssistantPanel />
        </div>
      }
      sidebarFooter={(collapsed) => <UserMenu compact={collapsed} />}
      rightInset={open && !isMobile ? ASSISTANT_DOCK_WIDTH : 0}
    >
      {children}
    </AppShell>
  );
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <AssistantDockProvider>
        <Shell>{children}</Shell>
      </AssistantDockProvider>
    </RequireAuth>
  );
}
