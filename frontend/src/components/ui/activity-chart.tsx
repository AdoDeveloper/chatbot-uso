"use client";

import { useMemo } from "react";
import { BarChart, Bar, XAxis, YAxis, CartesianGrid } from "recharts";
import type { HeatmapCell, HeatmapWindow } from "@/types";
import { ChartContainer, ChartTooltip, ChartTooltipContent, type ChartConfig } from "@/components/ui/chart";

const DAYS_ES = ["Dom", "Lun", "Mar", "Mié", "Jue", "Vie", "Sáb"];
const MONTH_LABELS = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];

interface ActivityChartProps {
  cells: HeatmapCell[];
  window?: HeatmapWindow;
  rangeStart?: string | null;
  rangeEnd?: string | null;
}

const chartConfig = {
  count: { label: "Consultas", color: "#0F2F6E" },
} satisfies ChartConfig;

/**
 * Antes un heatmap de cuadros de color (estilo GitHub) para los 4 modos.
 * En móvil las celdas se volvían ilegibles (demasiado pequeñas, sin espacio
 * para 24 columnas). Reemplazado por gráficos de barras — mismo dato,
 * consistente con el resto de Estadísticas, legible en cualquier ancho.
 */
export function ActivityChart({ cells, window = "week", rangeEnd }: ActivityChartProps) {
  if (window === "day") return <DayBars cells={cells} />;
  if (window === "week") return <WeekBars cells={cells} />;
  if (window === "month") return <MonthBars cells={cells} rangeEnd={rangeEnd} />;
  return <YearBars cells={cells} rangeEnd={rangeEnd} />;
}

function EmptyNote({ children }: { children: React.ReactNode }) {
  return <p className="text-2xs text-muted-foreground mt-2">{children}</p>;
}

function DayBars({ cells }: { cells: HeatmapCell[] }) {
  const data = useMemo(() => {
    const byHour = new Map<number, number>();
    cells.forEach((c) => { if (c.hour != null) byHour.set(c.hour, c.count); });
    return Array.from({ length: 24 }, (_, h) => ({
      label: `${String(h).padStart(2, "0")}h`,
      count: byHour.get(h) ?? 0,
    }));
  }, [cells]);

  return (
    <>
      <ChartContainer config={chartConfig} className="h-52 w-full">
        <BarChart data={data} margin={{ left: -20 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} interval={2} fontSize={11} />
          <YAxis tickLine={false} axisLine={false} allowDecimals={false} fontSize={11} />
          <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
          <Bar dataKey="count" fill="var(--color-count)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ChartContainer>
      <EmptyNote>Distribución por hora en las últimas 24 h</EmptyNote>
    </>
  );
}

function WeekBars({ cells }: { cells: HeatmapCell[] }) {
  // Colapsa la matriz día×hora sumando las 24 horas de cada día: pierde el
  // detalle de hora del día pero conserva el insight principal (qué día de
  // la semana concentra más actividad).
  const data = useMemo(() => {
    const byDay = new Map<number, number>();
    cells.forEach((c) => {
      if (c.day != null) byDay.set(c.day, (byDay.get(c.day) ?? 0) + c.count);
    });
    return DAYS_ES.map((label, d) => ({ label, count: byDay.get(d) ?? 0 }));
  }, [cells]);

  return (
    <>
      <ChartContainer config={chartConfig} className="h-52 w-full">
        <BarChart data={data} margin={{ left: -20 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={11} />
          <YAxis tickLine={false} axisLine={false} allowDecimals={false} fontSize={11} />
          <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
          <Bar dataKey="count" fill="var(--color-count)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ChartContainer>
      <EmptyNote>Suma por día de la semana — últimos 30 días</EmptyNote>
    </>
  );
}

function MonthBars({ cells, rangeEnd }: { cells: HeatmapCell[]; rangeEnd?: string | null }) {
  const data = useMemo(() => {
    const byDate = new Map<string, number>();
    cells.forEach((c) => { if (c.date) byDate.set(c.date, c.count); });
    const end = rangeEnd ? new Date(rangeEnd) : new Date();
    const days: { iso: string; label: string; count: number }[] = [];
    for (let i = 29; i >= 0; i--) {
      const d = new Date(end);
      d.setUTCDate(d.getUTCDate() - i);
      const iso = d.toISOString().slice(0, 10);
      days.push({ iso, label: `${String(d.getUTCDate()).padStart(2, "0")}/${d.getUTCMonth() + 1}`, count: byDate.get(iso) ?? 0 });
    }
    return days;
  }, [cells, rangeEnd]);

  return (
    <>
      <ChartContainer config={chartConfig} className="h-52 w-full">
        <BarChart data={data} margin={{ left: -20 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} interval={3} fontSize={11} />
          <YAxis tickLine={false} axisLine={false} allowDecimals={false} fontSize={11} />
          <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
          <Bar dataKey="count" fill="var(--color-count)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ChartContainer>
      <EmptyNote>Consultas diarias en el último mes</EmptyNote>
    </>
  );
}

function YearBars({ cells, rangeEnd }: { cells: HeatmapCell[]; rangeEnd?: string | null }) {
  // Suma por mes en vez de 365 puntos diarios: la vista anual busca
  // tendencia general (qué meses concentran más uso), no el detalle de un día.
  const data = useMemo(() => {
    const end = rangeEnd ? new Date(rangeEnd) : new Date();
    const byMonth = new Map<string, number>();
    cells.forEach((c) => {
      if (!c.date) return;
      const key = c.date.slice(0, 7); // YYYY-MM
      byMonth.set(key, (byMonth.get(key) ?? 0) + c.count);
    });
    const months: { key: string; label: string; count: number }[] = [];
    for (let i = 11; i >= 0; i--) {
      const d = new Date(end.getUTCFullYear(), end.getUTCMonth() - i, 1);
      const key = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
      months.push({ key, label: MONTH_LABELS[d.getMonth()], count: byMonth.get(key) ?? 0 });
    }
    return months;
  }, [cells, rangeEnd]);

  return (
    <>
      <ChartContainer config={chartConfig} className="h-52 w-full">
        <BarChart data={data} margin={{ left: -20 }}>
          <CartesianGrid vertical={false} strokeDasharray="3 3" />
          <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={11} />
          <YAxis tickLine={false} axisLine={false} allowDecimals={false} fontSize={11} />
          <ChartTooltip cursor={false} content={<ChartTooltipContent />} />
          <Bar dataKey="count" fill="var(--color-count)" radius={[3, 3, 0, 0]} />
        </BarChart>
      </ChartContainer>
      <EmptyNote>Suma mensual — últimos 12 meses</EmptyNote>
    </>
  );
}
