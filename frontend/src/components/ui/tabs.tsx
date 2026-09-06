"use client";

import { Tabs as HeroTabs } from "@heroui/react";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

type TabsProps = ComponentProps<typeof HeroTabs> & { value?: string; defaultValue?: string; onValueChange?: (value: string) => void };
export function Tabs({ value, defaultValue, onValueChange, className, ...props }: TabsProps) {
  return <HeroTabs selectedKey={value} defaultSelectedKey={defaultValue} onSelectionChange={(key) => onValueChange?.(String(key))} className={cn("leon-tabs gap-5", className)} {...props} />;
}
export function TabsList({ className, ...props }: ComponentProps<typeof HeroTabs.List>) {
  return <HeroTabs.List aria-label="Разделы" className={cn(className, "max-w-full mb-0")} {...props} />;
}
export function TabsTrigger({ value, disabled, children, ...props }: Omit<ComponentProps<typeof HeroTabs.Tab>, "id" | "children"> & { value: string; disabled?: boolean; children: ReactNode }) {
  return <HeroTabs.Tab id={value} isDisabled={disabled} {...props}>{children}<HeroTabs.Indicator /></HeroTabs.Tab>;
}
export function TabsContent({ value, className, ...props }: Omit<ComponentProps<typeof HeroTabs.Panel>, "id"> & { value: string }) {
  return <HeroTabs.Panel id={value} className={cn(className, "leon-tab-panel m-0 p-0")} {...props} />;
}
