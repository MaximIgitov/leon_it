"use client";

import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { PERIOD_LABELS, type DashboardPeriod } from "@/lib/api/dashboard";

const PERIODS: DashboardPeriod[] = ["7", "30", "90", "all"];

export function PeriodSwitch({
  value,
  onChange,
}: {
  value: DashboardPeriod;
  onChange: (period: DashboardPeriod) => void;
}) {
  return (
    <Tabs value={value} onValueChange={(next) => onChange(next as DashboardPeriod)}>
      <TabsList aria-label="Период" className="h-9">
        {PERIODS.map((period) => (
          <TabsTrigger key={period} value={period} className="px-2.5 text-xs sm:px-3 sm:text-sm">
            {PERIOD_LABELS[period]}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
