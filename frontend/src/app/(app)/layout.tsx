"use client";

import { RequireAuth } from "@/components/auth/auth-provider";
import { AppShell } from "@/components/layout/app-shell";
import { UserMenu } from "@/components/layout/user-menu";

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <RequireAuth>
      <AppShell sidebarFooter={(collapsed) => <UserMenu compact={collapsed} />}>
        {children}
      </AppShell>
    </RequireAuth>
  );
}
