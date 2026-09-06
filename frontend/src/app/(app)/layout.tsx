"use client";

import { AssistantPanel, AssistantTrigger } from "@/components/assistant/assistant-panel";
import { AssistantDockProvider } from "@/components/assistant/dock";
import { RequireAuth, useAuth } from "@/components/auth/auth-provider";
import { AppShell } from "@/components/layout/app-shell";
import { UserMenu } from "@/components/layout/user-menu";
import { ThemeSwitch } from "@/components/ui/theme-switch";
import { HiringJourneyProvider, HiringJourneyTrigger } from "@/components/onboarding/hiring-journey";

function Shell({ children }: { children: React.ReactNode }) {
  const { me } = useAuth();
  return (
    <HiringJourneyProvider key={`${me?.organization.id}:${me?.id}`}>
    <AppShell
      header={
        <div className="ml-auto flex items-center gap-2">
          <ThemeSwitch />
          <AssistantTrigger />
        </div>
      }
      sidebarFooter={(collapsed, onNavigate) => <><HiringJourneyTrigger compact={collapsed} onOpen={onNavigate} /><UserMenu compact={collapsed} /></>}
      assistant={<AssistantPanel />}
    >
      {children}
    </AppShell>
    </HiringJourneyProvider>
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
