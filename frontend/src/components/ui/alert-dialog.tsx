"use client";

import { Modal } from "@heroui/react";
import type { ComponentProps, ReactNode } from "react";
import { Button, type ButtonProps } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export { Dialog as AlertDialog, DialogTrigger as AlertDialogTrigger, DialogHeader as AlertDialogHeader, DialogFooter as AlertDialogFooter, DialogTitle as AlertDialogTitle, DialogDescription as AlertDialogDescription } from "./dialog";
export function AlertDialogContent({ className, children, ...props }: Omit<ComponentProps<typeof Modal.Dialog>, "children"> & { children: ReactNode }) {
  return <Modal.Backdrop variant="opaque" isDismissable={false}><Modal.Container size="lg" placement="center"><Modal.Dialog role="alertdialog" className={cn("leon-modal grid max-h-full gap-5 overflow-y-auto p-6", className)} {...props}>{children}</Modal.Dialog></Modal.Container></Modal.Backdrop>;
}
export function AlertDialogAction(props: ButtonProps) {
  return <Button slot="close" variant="destructive" {...props} />;
}
export function AlertDialogCancel(props: ButtonProps) {
  return <Button slot="close" variant="outline" autoFocus {...props} />;
}
