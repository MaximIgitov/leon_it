"use client";

import { AssistantPanel } from "@/components/assistant/assistant-panel";
import { RequireAuth } from "@/components/auth/auth-provider";
import { AppShell } from "@/components/layout/app-shell";
import { UserMenu } from "@/components/layout/user-menu";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <AppShell
        header={
          <div className="ml-auto flex items-center gap-2">
            <AssistantPanel />
          </div>
        }
        sidebarFooter={(collapsed) => <UserMenu compact={collapsed} />}
      >
        {children}
      </AppShell>
    </RequireAuth>
  );
}
