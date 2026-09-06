"use client";

import type { ComponentProps } from "react";
import { Chip } from "@heroui/react";
import { cn } from "@/lib/utils";

export interface BadgeProps extends Omit<ComponentProps<"span">, "color"> {
  variant?: "default" | "secondary" | "destructive" | "outline";
}
export function Badge({ className, variant = "default", children, ...props }: BadgeProps) {
  return <Chip size="sm" color={variant === "destructive" ? "danger" : variant === "default" ? "success" : "default"} variant={variant === "outline" ? "secondary" : "soft"} className={cn("leon-badge", className)} {...props}>{children}</Chip>;
}
