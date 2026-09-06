"use client";

import { useRouter } from "@/lib/router";
import { ChevronUp, LogOut } from "lucide-react";

import { useAuth } from "@/components/auth/auth-provider";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Dropdown } from "@heroui/react";
import { roleLabel } from "@/lib/roles";
import { cn } from "@/lib/utils";

function initials(name: string | null, email: string): string {
  const source = name?.trim() || email;
  return source
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

export function UserMenu({ compact }: { compact: boolean }) {
  const { me, signOut } = useAuth();
  const router = useRouter();
  if (!me) return null;

  return (
    <Dropdown>
      <Dropdown.Trigger
          type="button"
          className={cn(
            "flex w-full items-center gap-2 rounded-2xl p-2 text-left transition-colors hover:bg-secondary",
            compact && "justify-center",
          )}
          aria-label="Меню пользователя"
        >
          <Avatar className="h-8 w-8">
            <AvatarFallback className="bg-primary/10 text-xs font-extrabold text-primary">
              {initials(me.full_name, me.email)}
            </AvatarFallback>
          </Avatar>
          {!compact && (
            <>
              <span className="min-w-0 flex-1">
                <span className="block truncate text-sm font-medium">
                  {me.full_name ?? me.email}
                </span>
                <span className="block truncate text-xs text-muted-foreground">
                  {roleLabel(me.role)} · {me.organization.name}
                </span>
              </span>
              <ChevronUp className="h-4 w-4 shrink-0 text-muted-foreground" />
            </>
          )}
        </Dropdown.Trigger>
      <Dropdown.Popover placement="top end" className="w-64 rounded-3xl p-2">
        <div className="mb-1 border-b px-3 py-3">
          <span className="block truncate text-sm font-medium">{me.full_name ?? me.email}</span>
          <span className="block truncate text-xs text-muted-foreground">{me.email}</span>
        </div>
        <Dropdown.Menu aria-label="Аккаунт">
        <Dropdown.Item id="sign-out" textValue="Выйти"
          onAction={() => {
            signOut();
            router.replace("/login");
          }}
        >
          <LogOut className="mr-2 h-4 w-4" />
          Выйти
        </Dropdown.Item>
        </Dropdown.Menu>
      </Dropdown.Popover>
    </Dropdown>
  );
}
