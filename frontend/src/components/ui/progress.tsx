"use client";

import { ProgressBar } from "@heroui/react";
import type { ComponentProps } from "react";

export function Progress({ value, max, ...props }: Omit<ComponentProps<typeof ProgressBar>, "value"> & { value?: number | null; max?: number }) {
  return <ProgressBar aria-label="Прогресс интервью" {...props} value={value ?? 0} maxValue={max}>
    <ProgressBar.Track><ProgressBar.Fill /></ProgressBar.Track>
  </ProgressBar>;
}
