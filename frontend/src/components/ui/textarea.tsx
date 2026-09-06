"use client";

import * as React from "react";
import { TextArea } from "@heroui/react";
import { cn } from "@/lib/utils";

export const Textarea = React.forwardRef<HTMLTextAreaElement, React.ComponentProps<"textarea">>(function Textarea({ className, ...props }, ref) {
  return <TextArea ref={ref} className={cn("leon-input min-h-24 w-full code-scrollbar", className)} {...props} />;
});
