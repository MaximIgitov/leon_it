"use client";

import * as React from "react";
import { Button as HeroButton, buttonVariants as heroButtonVariants } from "@heroui/react";
import { cn } from "@/lib/utils";

type Variant = "default" | "destructive" | "outline" | "secondary" | "ghost" | "link";
type Size = "default" | "sm" | "lg" | "icon";
const variants = { default: "primary", destructive: "danger", outline: "outline", secondary: "secondary", ghost: "ghost", link: "ghost" } as const;
export interface ButtonProps extends Omit<React.ComponentProps<typeof HeroButton>, "variant" | "size" | "className" | "children"> {
  title?: string;
  className?: string;
  children?: React.ReactNode;
  disabled?: boolean;
  variant?: Variant;
  size?: Size;
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant = "default", size = "default", asChild, disabled, children, ...props }, ref,
) {
  const heroProps = { variant: variants[variant], size: size === "default" || size === "icon" ? "md" as const : size, isIconOnly: size === "icon" };
  const classes = cn("leon-button", variant === "link" && "text-primary underline-offset-4 hover:underline", className);
  if (asChild && React.isValidElement<{ className?: string }>(children)) {
    return React.cloneElement(children, { ...props, className: cn(heroButtonVariants(heroProps), classes, children.props.className) });
  }
  return <HeroButton ref={ref} {...heroProps} isDisabled={disabled} className={classes} {...props}>{children}</HeroButton>;
});
