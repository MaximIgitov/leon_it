"use client";

import { Modal } from "@heroui/react";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Dialog({ open, defaultOpen, onOpenChange, children }: { open?: boolean; defaultOpen?: boolean; onOpenChange?: (open: boolean) => void; children: ReactNode }) {
  return <Modal isOpen={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>{children}</Modal>;
}
export function DialogTrigger({ children }: { asChild?: boolean; children: ReactNode }) {
  return <>{children}</>;
}
export function DialogContent({ className, children, ...props }: Omit<ComponentProps<typeof Modal.Dialog>, "children"> & { children: ReactNode }) {
  return <Modal.Backdrop variant="opaque"><Modal.Container size="lg" placement="center" className="leon-modal-container"><Modal.Dialog className={cn("leon-modal grid max-h-full gap-5 overflow-y-auto p-6", className)} {...props}>
    {children}<Modal.CloseTrigger aria-label="Закрыть" />
  </Modal.Dialog></Modal.Container></Modal.Backdrop>;
}
export function DialogHeader({ className, ...props }: ComponentProps<"div">) {
  return <Modal.Header className={cn("space-y-2 pr-7", className)} {...props} />;
}
export function DialogFooter({ className, ...props }: ComponentProps<"div">) {
  return <Modal.Footer className={cn("flex flex-wrap justify-end gap-3", className)} {...props} />;
}
export const DialogTitle = Modal.Heading;
export function DialogDescription({ className, ...props }: ComponentProps<"p">) {
  return <p className={cn("text-sm leading-relaxed text-muted-foreground", className)} {...props} />;
}
