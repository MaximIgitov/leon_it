"use client";

import {
  Line,
  LineChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipProps,
} from "recharts";

import type { TimeseriesPoint } from "@/lib/api/dashboard";

import { formatDay, formatDayLong } from "./format";

/*
 * График по дням на Recharts. Цвета берутся из CSS-переменных темы, поэтому
 * тёмная схема подхватывается без отдельной палитры. Компонент подключается
 * через dynamic(..., { ssr: false }): ResponsiveContainer меряет контейнер в
 * браузере, а на сервере ему нечего мерить.
 */
const SERIES = [
  { key: "invited", label: "Приглашено", color: "var(--chart-blue)" },
  { key: "completed", label: "Завершено", color: "var(--brand-green)" },
  { key: "evaluated", label: "Оценено", color: "var(--chart-orange)" },
] as const;

function ChartTooltip({ active, payload, label }: TooltipProps<number, string>) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <p className="mb-1 font-medium">{formatDayLong(String(label))}</p>
      <ul className="space-y-0.5">
        {payload.map((item) => (
          <li key={item.dataKey} className="flex items-center justify-between gap-4">
            <span className="flex items-center gap-1.5 text-muted-foreground">
              <span className="h-2 w-2 rounded-full" style={{ background: item.color }} />
              {item.name}
            </span>
            <span className="tabular-nums">{item.value}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default function DailyChart({ points }: { points: TimeseriesPoint[] }) {
  const axisStyle = { fill: "var(--muted-foreground)", fontSize: 11 };
  return (
    <div className="space-y-3">
      <div className="h-64 w-full">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={points} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>

            <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
            <XAxis
              dataKey="date"
              tickFormatter={formatDay}
              tick={axisStyle}
              tickLine={false}
              axisLine={{ stroke: "var(--border)" }}
              minTickGap={28}
            />
            <YAxis allowDecimals={false} tick={axisStyle} tickLine={false} axisLine={false} width={44} />
            <Tooltip content={<ChartTooltip />} cursor={{ stroke: "var(--border)" }} />
            {SERIES.map((series) => (
              <Line
                key={series.key}
                type="monotone"
                dataKey={series.key}
                name={series.label}
                stroke={series.color}
                strokeWidth={series.key === "completed" ? 3 : 2}
                strokeLinecap="round"
                strokeLinejoin="round"
                dot={{ r: 2, fill: series.color, strokeWidth: 0 }}
                activeDot={{ r: 4, strokeWidth: 0 }}
                isAnimationActive={false}
              />
            ))}
          </LineChart>
        </ResponsiveContainer>
      </div>
      <ul className="flex flex-wrap gap-x-4 gap-y-1 text-xs text-muted-foreground" aria-label="Легенда">
        {SERIES.map((series) => (
          <li key={series.key} className="flex items-center gap-1.5">
            <span className="h-2 w-2 rounded-full" style={{ background: series.color }} />
            {series.label}
          </li>
        ))}
      </ul>
    </div>
  );
}
