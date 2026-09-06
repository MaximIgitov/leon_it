"use client";

import { Checkbox as HeroCheckbox, Label } from "@heroui/react";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

type CheckboxProps = Omit<ComponentProps<typeof HeroCheckbox>, "onChange" | "children"> & {
  checked?: boolean | "indeterminate";
  defaultChecked?: boolean;
  disabled?: boolean;
  onCheckedChange?: (checked: boolean) => void;
  children?: ReactNode;
};
export function Checkbox({ checked, defaultChecked, disabled, onCheckedChange, className, children, ...props }: CheckboxProps) {
  return <HeroCheckbox {...props} isSelected={checked === undefined ? undefined : checked === true} defaultSelected={defaultChecked} isIndeterminate={checked === "indeterminate"} isDisabled={disabled} onChange={onCheckedChange} className={cn("leon-checkbox shrink-0", typeof className === "string" && className)}>
    <HeroCheckbox.Content><HeroCheckbox.Control><HeroCheckbox.Indicator /></HeroCheckbox.Control>{children && <Label>{children}</Label>}</HeroCheckbox.Content>
  </HeroCheckbox>;
}
