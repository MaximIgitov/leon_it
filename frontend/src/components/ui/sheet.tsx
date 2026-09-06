"use client";

import { Modal } from "@heroui/react";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";
export { Dialog as Sheet, DialogTrigger as SheetTrigger, DialogTitle as SheetTitle } from "./dialog";

export function SheetContent({ side = "right", className, children, ...props }: Omit<ComponentProps<typeof Modal.Dialog>, "children"> & { children: ReactNode } & { side?: "left" | "right" }) {
  return <Modal.Backdrop variant="opaque"><Modal.Container className={cn("leon-sheet-container", side === "left" ? "leon-sheet-left" : "leon-sheet-right")}><Modal.Dialog className={cn("leon-sheet h-dvh w-80 max-w-[85vw] rounded-none p-6", className)} {...props}>{children}<Modal.CloseTrigger aria-label="Закрыть меню" /></Modal.Dialog></Modal.Container></Modal.Backdrop>;
}
