"use client";

import { Switch as HeroSwitch } from "@heroui/react";
import type { ComponentProps } from "react";

type SwitchProps = Omit<ComponentProps<typeof HeroSwitch>, "onChange"> & {
  checked?: boolean;
  defaultChecked?: boolean;
  disabled?: boolean;
  onCheckedChange?: (checked: boolean) => void;
};
export function Switch({ checked, defaultChecked, disabled, onCheckedChange, ...props }: SwitchProps) {
  return <HeroSwitch {...props} isSelected={checked} defaultSelected={defaultChecked} isDisabled={disabled} onChange={onCheckedChange}>
    <HeroSwitch.Content><HeroSwitch.Control><HeroSwitch.Thumb /></HeroSwitch.Control></HeroSwitch.Content>
  </HeroSwitch>;
}
