"use client";

import { Skeleton } from "@heroui/react";
export { Skeleton };

export function PageSkeleton() {
  return <div role="status" aria-label="Загрузка" className="space-y-5 w-full">
    <Skeleton className="h-9 w-2/5 rounded-xl" />
    <Skeleton className="h-12 w-full rounded-2xl" />
    <div className="grid gap-5 sm:grid-cols-2"><Skeleton className="h-52 rounded-3xl" /><Skeleton className="h-52 rounded-3xl" /></div>
    <Skeleton className="h-32 w-full rounded-3xl" />
  </div>;
}

export function RowsSkeleton() {
  return <div role="status" aria-label="Загрузка" className="space-y-4 w-full">
    {[0, 1, 2].map((row) => <div key={row} className="flex items-center gap-4"><Skeleton className="h-11 w-11 shrink-0 rounded-xl" /><div className="flex-1 space-y-2"><Skeleton className="h-4 w-2/3 rounded-lg" /><Skeleton className="h-3 w-1/3 rounded-lg" /></div></div>)}
  </div>;
}
