"use client";

import { toast as notify } from "@heroui/react";
import { createElement, type ReactNode } from "react";
import { CelebrationMark } from "@/components/ui/celebration-mark";

type ToastOptions = { title?: ReactNode; description?: ReactNode; variant?: "default" | "destructive"; duration?: number; celebrate?: boolean };
export function toast({ title, description, variant, duration, celebrate }: ToastOptions) {
  const id = notify(title, { description, variant: variant === "destructive" ? "danger" : "success", timeout: duration,
    ...(celebrate && variant !== "destructive" ? { indicator: createElement(CelebrationMark) } : {}),
  });
  return { id, dismiss: () => notify.close(id) };
}
export function useToast() {
  return { toast, dismiss: (id?: string) => id ? notify.close(id) : notify.clear() };
}
