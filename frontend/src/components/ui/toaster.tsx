"use client";

import { Toast } from "@heroui/react";

export function Toaster() {
  return <Toast.Provider placement="bottom end" maxVisibleToasts={3} />;
}
