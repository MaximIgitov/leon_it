"use client";

import * as React from "react";
import { ListBox, Select as HeroSelect } from "@heroui/react";
import { cn } from "@/lib/utils";

type SelectProps = Omit<React.ComponentProps<typeof HeroSelect>, "onChange" | "value" | "defaultValue" | "children"> & {
  children: React.ReactNode;
  value?: string;
  defaultValue?: string;
  disabled?: boolean;
  onValueChange?: (value: string) => void;
};
export function Select({ value, defaultValue, disabled, onValueChange, className, children, ...props }: SelectProps) {
  // The existing screens put the label and placeholder on their trigger.
  const trigger = React.Children.toArray(children as React.ReactNode).find((child) => React.isValidElement(child) && child.type === SelectTrigger) as React.ReactElement<React.ComponentProps<typeof SelectTrigger>> | undefined;
  const display = React.Children.toArray(trigger?.props.children).find((child) => React.isValidElement(child) && child.type === SelectValue) as React.ReactElement<{ placeholder?: string }> | undefined;
  return <HeroSelect {...props} aria-label={props["aria-label"] ?? trigger?.props["aria-label"] ?? display?.props.placeholder ?? "Выберите значение"} placeholder={display?.props.placeholder} selectedKey={value === undefined ? undefined : value || null} defaultSelectedKey={defaultValue} isDisabled={disabled} onSelectionChange={(key) => onValueChange?.(String(key))} className={cn("leon-select", typeof className === "string" && className)}>{children}</HeroSelect>;
}
export function SelectTrigger({ className, children, ...props }: Omit<React.ComponentProps<typeof HeroSelect.Trigger>, "children"> & { children: React.ReactNode }) {
  return <HeroSelect.Trigger className={cn("leon-select-trigger w-full", typeof className === "string" && className)} {...props}>{children}<HeroSelect.Indicator /></HeroSelect.Trigger>;
}
export function SelectValue({ placeholder: _placeholder, ...props }: React.ComponentProps<typeof HeroSelect.Value> & { placeholder?: string }) {
  return <HeroSelect.Value {...props} />;
}
export function SelectContent({ children, className }: { children: React.ReactNode; className?: string }) {
  return <HeroSelect.Popover className={className} placement="bottom start"><ListBox>{children}</ListBox></HeroSelect.Popover>;
}
export function SelectItem({ value, children, disabled, ...props }: Omit<React.ComponentProps<typeof ListBox.Item>, "id" | "children"> & { value: string; disabled?: boolean; children: React.ReactNode }) {
  return <ListBox.Item id={value} isDisabled={disabled} textValue={React.Children.toArray(children).filter((child) => typeof child === "string" || typeof child === "number").join("")} {...props}>{children}<ListBox.ItemIndicator /></ListBox.Item>;
}
