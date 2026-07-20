"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import {
  BarChart3, TrendingUp, Users, MessageSquare, Clock,
  Rocket, Circle,
  Download, AlertTriangle, ArrowUp, ArrowDown, Minus, Globe, Code, Play, Zap, MapPin,
  ThumbsUp, ThumbsDown, Loader2,
} from "lucide-react";
import {
 BarChart, Bar, XAxis, YAxis, CartesianGrid,
 AreaChart, Area, PieChart, Pie, Cell as RCell,
 LineChart, Line, Legend,
} from "recharts";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { isoDay } from "@/lib/utils";
import { DataTable, type Column } from "@/components/composed/data-table";

type ActivityEventType =
  | "source_ingested" | "source_promoted" | "guardrail_block" | "escalation"
  | "provider_error" | "cache_cleared" | "user_login" | "version_snapshot"
  | "unanswered_spike" | "other";

interface ActivityEvent {
  id: string;
  type: ActivityEventType;
  title: string;
  detail: string | null;
  created_at: string;
  actor_name: string | null;
  href: string | null;
}

const ACTIVITY_LABEL: Record<ActivityEventType, string> = {
  source_ingested: "Fuente",
  source_promoted: "Publicado",
  guardrail_block: "Bloqueo",
  escalation: "Escalamiento",
  provider_error: "Error IA",
  cache_cleared: "Caché",
  user_login: "Acceso",
  version_snapshot: "Versión",
  unanswered_spike: "Pico",
  other: "Evento",
};
import type {
 AnalyticsDashboard, TopicStat, UnansweredGroup,
 PeriodComparison, ChannelStat, CacheStats, PageStat,
 TimeSeriesPoint,
} from "@/types";
import { ActivityChart } from "@/components/ui/activity-chart";
import { PageHeader } from "@/components/ui/page-header";

import { StatCard } from "@/components/composed/stat-card";
import { RefetchProgressBar } from "@/components/composed/refetch-progress-bar";
import { SegmentedControl } from "@/components/composed/segmented-control";
import { PeriodFilter } from "@/components/composed/period-filter";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { TableCell } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuTrigger, DropdownMenuContent, DropdownMenuItem } from "@/components/ui/dropdown-menu";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Progress } from "@/components/ui/progress";
import { HelpTip } from "@/components/ui/help-tip";
import { useToast } from "@/components/ui/toast";
import {
 ChartContainer,
 ChartTooltip,
 ChartTooltipContent,
 type ChartConfig,
} from "@/components/ui/chart";

// ── Colors ── (palette v2: institutional blues + forest green accent)
const CHART_NAVY = "#0F2F6E";  // brand mid-deep
const CHART_TEAL = "#0369A1";  // teal sub-acento
const CHART_GREEN = "#1FB107";  // forest green
const rateColor = (r: number) => r >= 90 ? "text-success" : r >= 70 ? "text-warning" : "text-destructive";

const topicsChartConfig = {
 count: { label: "Consultas", color: CHART_NAVY },
} satisfies ChartConfig;

const volumeChartConfig = {
 count: { label: "Consultas", color: CHART_NAVY },
} satisfies ChartConfig;

const latencyChartConfig = {
 avg_ms: { label: "Promedio", color: CHART_NAVY },
 p95_ms: { label: "P95", color: "#EF4444" },
} satisfies ChartConfig;

interface RouteStat { route: string; count: number; percentage: number }
interface LatencyPoint { date: string; avg_ms: number; p95_ms: number }
interface FeedbackSummary { positive: number; negative: number; total: number; positive_rate: number; days: number }
interface FeedbackTrend { date: string; positive: number; negative: number }
interface AnalyticsFeedback { summary: FeedbackSummary; trend: FeedbackTrend[] }
interface ActivityCell { hour?: number | null; day?: number | null; date?: string | null; count: number }
interface ActivityData {
 cells: ActivityCell[];
 window: "day" | "week" | "month" | "year";
 range_start: string | null;
 range_end: string | null;
}



const PIE_COLORS = [CHART_NAVY, CHART_TEAL, CHART_GREEN, "#F59E0B", "#EF4444", "#5BAFD4"];
const ROUTE_LABELS: Record<string, string> = { greeting: "Saludo", factual: "Factual", complex: "Complejo" };

function MetricasTab() {
 const { toast } = useToast();
 const today = isoDay(new Date());
 const [dateFrom, setDateFrom] = useState(isoDay(new Date(Date.now() - 6 * 86400000)));
 const [dateTo, setDateTo] = useState(today);
 const [exporting, setExporting] = useState(false);

  const [activityWindow, setActivityWindow] = useState<"day" | "week" | "month" | "year">("week");
 const [source, setSource] = useState<"production" | "playground">("production");

 // Un solo query param derivado del rango de fechas seleccionado.
 const periodQuery = `date_from=${dateFrom}&date_to=${dateTo}`;

 // No se consulta nada hasta tener ambas fechas de un rango válido.
 const periodReady = !!dateFrom && !!dateTo && dateFrom <= dateTo;

 // Días equivalentes al rango, usados por endpoints que aún piden `days`.
 const compDays = periodReady
  ? Math.max(1, Math.round((new Date(dateTo).getTime() - new Date(dateFrom).getTime()) / 86_400_000) + 1)
  : 7;

 const timelineDays = Math.min(compDays, 30);

 const src = `source=${source}`;

 // Un useApi por endpoint: cada sección refetchea solo cuando cambia SU query
 // (cambiar la ventana del heatmap ya no re-pide los otros 11 endpoints) y los
 // datos viejos siguen visibles durante recargas en vez de saltar a skeleton.
 const qMetrics = useApi<AnalyticsDashboard>(periodReady ? `/analytics/dashboard?${src}` : null);
 const qTopics = useApi<{ topics: TopicStat[]; days: number }>(periodReady ? `/analytics/topics?${periodQuery}&${src}` : null);
 const qActivity = useApi<ActivityData>(periodReady ? `/analytics/heatmap?window=${activityWindow}` : null);
 const qTimeseries = useApi<{ points: TimeSeriesPoint[] }>(periodReady ? `/analytics/timeseries?${periodQuery}&${src}` : null);
 const qRoutes = useApi<{ routes: RouteStat[] }>(periodReady ? `/analytics/routes?${periodQuery}&${src}` : null);
 const qLatency = useApi<{ points: LatencyPoint[] }>(periodReady ? `/analytics/latency/timeseries?${periodQuery}` : null);
  const qTimeline = useApi<{ events: ActivityEvent[]; days: number }>(periodReady ? `/analytics/timeline?days=${timelineDays}&limit=40` : null);
 const qComparison = useApi<PeriodComparison>(periodReady ? `/analytics/comparison?days=${compDays}&${src}` : null);
 const qChannels = useApi<{ channels: ChannelStat[]; days: number }>(periodReady ? `/analytics/channels?days=${compDays}` : null);
 const qCache = useApi<CacheStats>(periodReady ? `/analytics/cache?days=${compDays}` : null);
 const qPages = useApi<{ pages: PageStat[]; days: number }>(periodReady ? `/analytics/pages?days=${compDays}&${src}` : null);
 const qFeedback = useApi<AnalyticsFeedback>(periodReady ? `/analytics/feedback?days=${compDays}&${src}` : null);

 const queries = [
  qMetrics, qTopics, qActivity, qTimeseries, qRoutes, qLatency,
  qTimeline, qComparison, qChannels, qCache, qPages, qFeedback,
 ];
 const loading = queries.some((q) => q.loading);
 const refetching = queries.some((q) => q.refetching);
 const fetchError = queries.some((q) => q.error)
  ? "No se pudo cargar parte de las estadísticas. Inténtelo de nuevo más tarde."
  : null;

 const metrics = qMetrics.data;
 const topics = qTopics.data?.topics ?? [];
 const activity = qActivity.data;
 const timeseries = qTimeseries.data?.points ?? [];
 const routes = qRoutes.data?.routes ?? [];
 const latency = qLatency.data?.points ?? [];
 const timeline = qTimeline.data?.events ?? [];
 const comparison = qComparison.data;
 const channels = qChannels.data?.channels ?? [];
 const cache = qCache.data;
 const pages = qPages.data?.pages ?? [];
  const feedback = qFeedback.data;

  const showActor = true;
  const activityColumns: Column[] = [
    { id: "created_at", header: "Fecha/Hora", className: "w-28" },
    { id: "type", header: "Tipo", className: "w-28" },
    { id: "event", header: "Evento" },
    { id: "actor", header: "Actor", className: "w-36 hidden md:table-cell" },
  ];


 // Topics bar chart: dynamic height, no cap
 const chartHeight = Math.max(220, topics.length * 32);
 const chartData = topics.map((t) => ({
  name: t.topic.length > 22 ? t.topic.slice(0, 22) + "…" : t.topic,
  count: t.count,
  rate: t.resolution_rate,
 }));

 async function handleExport(fmt: "xlsx" | "pdf") {
  if (exporting) return;
  const rows: Record<string, string | number>[] = [];

  if (metrics) {
   rows.push({ Sección: "KPIs", Métrica: "Consultas hoy", Valor: metrics.queries_today });
   rows.push({ Sección: "KPIs", Métrica: "Tasa de resolución (%)", Valor: metrics.resolution_rate });
   rows.push({ Sección: "KPIs", Métrica: "Sesiones hoy", Valor: metrics.unique_users_today });
   rows.push({ Sección: "KPIs", Métrica: "Latencia promedio (ms)", Valor: metrics.avg_latency_ms.toFixed(0) });
  }

  topics.forEach((t) => rows.push({ Sección: "Temas", Métrica: t.topic, Valor: t.count, "Tasa resolución (%)": t.resolution_rate.toFixed(1) }));
  timeseries.forEach((p) => rows.push({ Sección: "Volumen diario", Métrica: p.date, Valor: p.count }));
  latency.forEach((p) => rows.push({ Sección: "Latencia diaria", Métrica: p.date, "Promedio (ms)": p.avg_ms.toFixed(0), "P95 (ms)": p.p95_ms.toFixed(0) }));

  setExporting(true);
  try {
   const resp = await api.post(`/analytics/export?format=${fmt}`, { rows }, { responseType: "blob" });
   const url = URL.createObjectURL(resp.data as Blob);
   const a = document.createElement("a");
   a.href = url;
   a.download = `estadisticas-${new Date().toISOString().slice(0, 10)}.${fmt}`;
   a.click();
   URL.revokeObjectURL(url);
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo exportar las estadísticas.") });
  } finally {
   setExporting(false);
  }
 }

 return (
  <div className="space-y-6">
   <RefetchProgressBar active={refetching} />

   {/* Source toggle + Period selector + export */}
   <div className="flex flex-wrap items-center justify-between gap-3">
    <div className="flex flex-wrap items-center gap-3">
     {/* Source toggle */}
     <SegmentedControl
      ariaLabel="Fuente de datos"
      value={source}
      onChange={setSource}
      options={[
       { value: "production", label: "Producción", icon: Rocket },
       { value: "playground", label: "Previsualizar", icon: Play },
      ]}
     />
     <div className="w-px h-5 bg-border" />
     {/* Selector de rango de fechas */}
     <PeriodFilter
      dateFrom={dateFrom}
      dateTo={dateTo}
      onDateFromChange={setDateFrom}
      onDateToChange={setDateTo}
      maxDate={today}
     />
    </div>

    {/* Export button */}
    <DropdownMenu>
     <DropdownMenuTrigger asChild>
      <Button variant="outline" size="sm" disabled={loading || !metrics || exporting} className="gap-1.5">
       {exporting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Download className="w-3.5 h-3.5" />} Exportar
      </Button>
     </DropdownMenuTrigger>
     <DropdownMenuContent align="end">
      <DropdownMenuItem onClick={() => handleExport("xlsx")}>Excel (.xlsx)</DropdownMenuItem>
      <DropdownMenuItem onClick={() => handleExport("pdf")}>PDF</DropdownMenuItem>
     </DropdownMenuContent>
    </DropdownMenu>
   </div>

   {/* Fetch error banner */}
   {fetchError && (
    <div className="flex items-start gap-2.5 px-4 py-3 rounded-xl border border-destructive/30 bg-destructive/5 text-sm text-destructive">
     <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
     <span>{fetchError}</span>
    </div>
   )}

   {/* Source indicator */}
   {source === "playground" && (
    <div className="flex items-center gap-2 px-3.5 py-2.5 rounded-lg border-l-4 border-warning bg-warning/10 text-warning-foreground">
     <Play className="w-3.5 h-3.5 shrink-0 text-warning" />
     <span className="text-xs font-medium text-foreground">
      Mostrando métricas de <strong>Previsualizar</strong> (sesiones de prueba internas).{" "}
      <Button
       type="button"
       variant="link"
       onClick={() => setSource("production")}
       className="h-auto p-0 text-xs font-semibold text-inherit underline underline-offset-2 hover:no-underline"
      >
       Cambiar a Producción
      </Button>
     </span>
    </div>
   )}

   {/* KPIs */}
   <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
    <StatCard title="Consultas hoy" value={metrics ? String(metrics.queries_today) : "—"} delta={metrics?.queries_today_delta} deltaLabel="vs. ayer" icon={MessageSquare} loading={loading} />
    <StatCard title="Tasa de resolución" value={metrics ? `${metrics.resolution_rate}%` : "—"} delta={metrics?.resolution_rate_delta} deltaLabel="vs. semana anterior" icon={TrendingUp} loading={loading} />
    <StatCard title="Sesiones hoy" value={metrics ? String(metrics.unique_users_today) : "—"} icon={Users} loading={loading} />
    <StatCard title="Latencia promedio" value={metrics ? `${(metrics.avg_latency_ms / 1000).toFixed(1)}s` : "—"} delta={metrics?.avg_latency_delta} deltaLabel="vs. semana anterior" icon={Clock} loading={loading} />
   </div>

   {/* Fase 5 — Comparativa entre períodos + canal + cache */}
   <PeriodComparisonPanel comparison={comparison} loading={loading} />

   <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
    <ChannelsPanel channels={channels} loading={loading} />
    <CacheStatsPanel cache={cache} loading={loading} />
   </div>

   <PagesPanel pages={pages} loading={loading} />

   <FeedbackPanel feedback={feedback} loading={loading} />

   <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
    {/* Top topics — Recharts bar chart (no cap, scrollable) */}
    <Card>
     <CardHeader>
      <div className="flex items-center justify-between">
       <div>
        <CardTitle className="text-15">Temas más consultados</CardTitle>
        <CardDescription>{topics.length > 0 ? `${topics.length} temas` : "Sin datos aún"}</CardDescription>
       </div>
       <BarChart3 className="h-4 w-4 text-muted-foreground" />
      </div>
     </CardHeader>
     <CardContent>
      {loading ? (
       <div className="space-y-3">{[1,2,3,4].map(i => <Skeleton key={i} className="h-6 w-full" />)}</div>
      ) : topics.length === 0 ? (
       <EmptyState icon={BarChart3} title="Sin datos aún" description="Las consultas generarán estadísticas de temas" />
      ) : (
       <div className="max-h-100 overflow-y-auto pr-1">
        <ChartContainer config={topicsChartConfig} className="aspect-auto!" style={{ height: chartHeight }}>
         <BarChart data={chartData} layout="vertical" margin={{ left: 0, right: 16, top: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" horizontal={false} />
          <XAxis type="number" tickLine={false} axisLine={false} />
          <YAxis dataKey="name" type="category" width={130} tickLine={false} axisLine={false} />
          <ChartTooltip cursor={false} content={<ChartTooltipContent hideLabel />} />
          <Bar dataKey="count" radius={[0, 4, 4, 0]} fill="var(--color-count)" maxBarSize={24} />
         </BarChart>
        </ChartContainer>
       </div>
      )}
     </CardContent>
    </Card>

    {/* Resolution rate by topic */}
    <Card>
     <CardHeader>
      <CardTitle className="text-15">Tasa de resolución por tema</CardTitle>
      <CardDescription>Porcentaje respondido correctamente</CardDescription>
     </CardHeader>
     <CardContent>
      {loading ? (
       <div className="space-y-3">{[1,2,3,4].map(i => <Skeleton key={i} className="h-6 w-full" />)}</div>
      ) : topics.length === 0 ? (
       <EmptyState icon={TrendingUp} title="Sin datos aún" />
      ) : (
       <div className="space-y-3.5 max-h-100 overflow-y-auto pr-1">
        {topics.map((topic) => (
         <div key={topic.topic} className="flex items-center gap-3">
          <span className="w-36 truncate text-sm">{topic.topic}</span>
          <div className="flex-1">
           <Progress
            value={topic.resolution_rate}
            indicatorClassName={
             topic.resolution_rate >= 90 ? "bg-success" :
             topic.resolution_rate >= 70 ? "bg-warning" : "bg-destructive"
            }
           />
          </div>
          <span className={`w-10 text-right text-xs font-medium ${rateColor(topic.resolution_rate)}`}>
           {topic.resolution_rate.toFixed(0)}%
          </span>
         </div>
        ))}
       </div>
      )}
     </CardContent>
    </Card>
   </div>

   {/* Volume Timeseries + Route Distribution */}
   <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-6">
    <Card className="lg:col-span-2">
     <CardHeader>
      <CardTitle className="text-15">Volumen de consultas</CardTitle>
      <CardDescription>Mensajes por día</CardDescription>
     </CardHeader>
     <CardContent>
      {loading ? (
       <Skeleton className="h-56 w-full" />
      ) : timeseries.length === 0 ? (
       <EmptyState icon={BarChart3} title="Sin datos" />
      ) : (
       <ChartContainer config={volumeChartConfig} className="aspect-auto! h-56">
        <AreaChart data={timeseries} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
         <defs>
          <linearGradient id="colorCount" x1="0" y1="0" x2="0" y2="1">
           <stop offset="5%" stopColor="var(--color-count)" stopOpacity={0.3} />
           <stop offset="95%" stopColor="var(--color-count)" stopOpacity={0} />
          </linearGradient>
         </defs>
         <CartesianGrid strokeDasharray="3 3" />
         <XAxis dataKey="date" tickLine={false} axisLine={false} tickFormatter={(v: string) => { const d = new Date(v); return `${d.getDate()}/${d.getMonth()+1}`; }} />
         <YAxis tickLine={false} axisLine={false} />
         <ChartTooltip cursor={false} content={<ChartTooltipContent indicator="dot" />} />
         <Area type="monotone" dataKey="count" stroke="var(--color-count)" fill="url(#colorCount)" strokeWidth={2} />
        </AreaChart>
       </ChartContainer>
      )}
     </CardContent>
    </Card>

    <Card>
     <CardHeader>
      <CardTitle className="text-15">Tipo de consulta</CardTitle>
      <CardDescription>Rutas RAG</CardDescription>
     </CardHeader>
     <CardContent>
      {loading ? (
       <Skeleton className="h-56 w-full" />
      ) : routes.length === 0 ? (
       <EmptyState icon={TrendingUp} title="Sin datos" />
      ) : (
       <ChartContainer config={{}} className="aspect-auto! h-56">
        <PieChart>
         <Pie data={routes} dataKey="count" nameKey="route" cx="50%" cy="50%" outerRadius={80} innerRadius={40} paddingAngle={3} label={({ route, percentage }: { route: string; percentage: number }) => `${ROUTE_LABELS[route] ?? route} ${percentage.toFixed(0)}%`}>
          {routes.map((_, i) => <RCell key={i} fill={PIE_COLORS[i % PIE_COLORS.length]} />)}
         </Pie>
         <ChartTooltip content={<ChartTooltipContent hideLabel formatter={(value, name) => [`${ROUTE_LABELS[String(name)] ?? name}: `, String(value)]} />} />
        </PieChart>
       </ChartContainer>
      )}
     </CardContent>
    </Card>
   </div>

   {/* Latency Trend */}
   <Card>
    <CardHeader>
     <CardTitle className="text-15">Tendencia de latencia</CardTitle>
     <CardDescription>Promedio y percentil 95 por día</CardDescription>
    </CardHeader>
    <CardContent>
     {loading ? (
      <Skeleton className="h-56 w-full" />
     ) : latency.length === 0 ? (
      <EmptyState icon={Clock} title="Sin datos de latencia" />
     ) : (
      <ChartContainer config={latencyChartConfig} className="aspect-auto! h-56">
       <LineChart data={latency} margin={{ left: 0, right: 8, top: 4, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="date" tickLine={false} axisLine={false} tickFormatter={(v: string) => { const d = new Date(v); return `${d.getDate()}/${d.getMonth()+1}`; }} />
        <YAxis tickLine={false} axisLine={false} tickFormatter={(v: number) => `${(v/1000).toFixed(1)}s`} />
        <ChartTooltip cursor={false} content={<ChartTooltipContent indicator="line" formatter={(v: unknown) => `${(Number(v)/1000).toFixed(2)}s`} />} />
        <Legend />
        <Line type="monotone" dataKey="avg_ms" name="Promedio" stroke="var(--color-avg_ms)" strokeWidth={2} dot={{ r: 3, strokeWidth: 0, fill: "var(--color-avg_ms)" }} isAnimationActive={latency.length > 1} />
        <Line type="monotone" dataKey="p95_ms" name="P95" stroke="var(--color-p95_ms)" strokeWidth={2} dot={{ r: 3, strokeWidth: 0, fill: "var(--color-p95_ms)" }} strokeDasharray="4 4" isAnimationActive={latency.length > 1} />
       </LineChart>
      </ChartContainer>
     )}
    </CardContent>
   </Card>

      {/* Activity chart */}
   <Card>
    <CardHeader>
     <div className="flex flex-wrap items-start justify-between gap-3">
      <div>
       <CardTitle className="text-15">Actividad por periodo</CardTitle>
       <CardDescription>
        {activityWindow === "day"  && "Consultas por hora en las últimas 24 h"}
        {activityWindow === "week" && "Consultas por día de la semana (últimos 30 días)"}
        {activityWindow === "month" && "Consultas diarias en el último mes"}
        {activityWindow === "year" && "Consultas por mes en el último año"}
       </CardDescription>
      </div>
      {/* Window selector */}
      <SegmentedControl
       ariaLabel="Rango del mapa"
       value={activityWindow}
        onChange={setActivityWindow}
       options={[
        { value: "day",  label: "Día" },
        { value: "week", label: "Semana" },
        { value: "month", label: "Mes" },
        { value: "year", label: "Año" },
       ]}
      />
     </div>
    </CardHeader>
    <CardContent>
      <ActivityChart
      cells={activity?.cells ?? []}
      window={activity?.window ?? activityWindow}
      rangeStart={activity?.range_start}
      rangeEnd={activity?.range_end}
     />
    </CardContent>
   </Card>

   {/* Timeline de eventos recientes */}
   <Card>
    <CardHeader>
     <div className="flex items-center justify-between">
      <div>
       <div className="flex items-center gap-1">
        <CardTitle className="text-15">Actividad reciente</CardTitle>
        <HelpTip
         description="Eventos relevantes del sistema: logins, bloqueos de guardrail, fuentes subidas, escalamientos, etc."
         side="bottom" align="start"
        />
       </div>
       <CardDescription>Últimos {timelineDays} días · {timeline.length} eventos</CardDescription>
      </div>
     </div>
    </CardHeader>
     <CardContent>
      {timeline.length === 0 ? (
       <EmptyState
        icon={Clock}
        title="Sin actividad reciente"
        description="Los eventos del sistema aparecerán aquí conforme ocurran"
       />
      ) : (
       <div className="max-h-[28rem] overflow-y-auto -mx-1">
        <DataTable<ActivityEvent>
          columns={activityColumns}
          data={timeline}
          rowKey={(e) => e.id}
          noCard
          renderRow={(e) => {
            const dt = new Date(e.created_at);
            const time = dt.toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit" });
            const day = dt.toLocaleDateString("es", { day: "2-digit", month: "short" });
            const row = (
              <>
                <TableCell className="whitespace-nowrap text-13 tabular-nums text-muted-foreground w-28">
                  <div className="flex flex-col leading-tight">
                    <span className="text-foreground">{time}</span>
                    <span className="text-3xs">{day}</span>
                  </div>
                </TableCell>
                <TableCell className="w-28">
                  <Badge variant="muted" size="xs">{ACTIVITY_LABEL[e.type]}</Badge>
                </TableCell>
                <TableCell>
                  <p className="text-13 font-medium text-foreground leading-snug">{e.title}</p>
                  {e.detail && <p className="text-2xs text-muted-foreground mt-0.5 leading-snug">{e.detail}</p>}
                </TableCell>
                <TableCell className="hidden md:table-cell w-36 text-2xs text-muted-foreground truncate">
                  {showActor && e.actor_name ? e.actor_name : "—"}
                </TableCell>
              </>
            );
            return e.href ? (
              <tr className="group hover:bg-muted/40 transition-colors">
                <TableCell className="p-0">
                  <Link href={e.href} className="block px-3 py-2.5 focus:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring">
                    {row}
                  </Link>
                </TableCell>
              </tr>
            ) : (
              <tr className="group hover:bg-muted/40 transition-colors">
                <TableCell className="px-3 py-2.5">{row}</TableCell>
              </tr>
            );
          }}
        />
       </div>
      )}
     </CardContent>
    </Card>
  </div>
 );
}

export default function AnaliticaPage() {
 const [pendingCount, setPendingCount] = useState<number | null>(null);

 useEffect(() => {
  api.get<{ groups: UnansweredGroup[]; total: number }>("/unanswered").then(({ data }) => {
   setPendingCount(data.total);
  }).catch(() => {});
 }, []);

 return (
  <div>
   <PageHeader
    icon={BarChart3}
    title="Estadísticas"
    tip="Métricas de uso, latencia y temas populares."
    action={pendingCount != null && pendingCount > 0 ? (
     <Button render={<Link href="/dashboard/conversaciones/pendientes" />} variant="outline" size="sm">
      <span className="inline-flex items-center justify-center h-5 min-w-5 px-1.5 rounded-full bg-destructive text-destructive-foreground text-3xs font-bold tabular-nums">{pendingCount}</span>
      <span>sin responder</span>
     </Button>
    ) : undefined}
   />

   <MetricasTab />
  </div>
 );
}

function PeriodComparisonPanel({ comparison, loading }: {
 comparison: PeriodComparison | null;
 loading: boolean;
}) {
 if (loading) {
  return <Skeleton className="h-32 w-full" />;
 }
 if (!comparison) return null;

 const fmtMs = (ms: number) => `${(ms / 1000).toFixed(1)}s`;
 const fmtPct = (n: number) => `${n.toFixed(1)}%`;
 const fmtRange = (start: string, end: string) => {
  const s = new Date(start);
  const e = new Date(end);
  // Formato corto y legible: "22 abr → 28 abr"
  const opts: Intl.DateTimeFormatOptions = { day: "2-digit", month: "short" };
  return `${s.toLocaleDateString("es", opts)} → ${e.toLocaleDateString("es", opts)}`;
 };

 const rows: Array<{ label: string; current: string; previous: string; delta: number; invertColor?: boolean; absolute?: boolean }> = [
  { label: "Consultas", current: String(comparison.current.queries), previous: String(comparison.previous.queries), delta: comparison.deltas.queries ?? 0 },
  { label: "Sesiones únicas", current: String(comparison.current.unique_sessions), previous: String(comparison.previous.unique_sessions), delta: comparison.deltas.unique_sessions ?? 0 },
  { label: "Resolución sin escalar", current: fmtPct(comparison.current.resolution_rate), previous: fmtPct(comparison.previous.resolution_rate), delta: comparison.deltas.resolution_rate ?? 0, absolute: true },
  { label: "Latencia promedio", current: fmtMs(comparison.current.avg_latency_ms), previous: fmtMs(comparison.previous.avg_latency_ms), delta: comparison.deltas.avg_latency_ms ?? 0, invertColor: true },
  { label: "Latencia P95", current: fmtMs(comparison.current.p95_latency_ms), previous: fmtMs(comparison.previous.p95_latency_ms), delta: comparison.deltas.p95_latency_ms ?? 0, invertColor: true },
 ];

 return (
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between gap-3 flex-wrap">
     <div className="flex items-center gap-2">
      <BarChart3 className="h-4 w-4 text-muted-foreground" />
      <CardTitle>Comparativa entre períodos</CardTitle>
     </div>
     <div className="flex items-center gap-2 text-xs">
      <Badge variant="default" className="font-mono tabular-nums">
       {fmtRange(comparison.current.range_start, comparison.current.range_end)}
      </Badge>
      <span className="text-muted-foreground">vs.</span>
      <Badge variant="muted" className="font-mono tabular-nums">
       {fmtRange(comparison.previous.range_start, comparison.previous.range_end)}
      </Badge>
     </div>
    </div>
   </CardHeader>
   <CardContent>
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-5 gap-3">
     {rows.map((r) => {
      const positive = r.delta > 0;
      const zero = r.delta === 0;
      const good = r.invertColor ? !positive && !zero : positive && !zero;
      const bad = r.invertColor ? positive : !positive && !zero && r.delta < 0;
      const Icon = zero ? Minus : positive ? ArrowUp : ArrowDown;
      const cls = zero ? "text-muted-foreground" : good ? "text-success" : bad ? "text-destructive" : "text-muted-foreground";
      return (
       <div key={r.label} className="border border-border rounded-lg p-4 bg-card hover:border-border/80 transition-colors">
        <p className="text-3xs uppercase tracking-wider text-muted-foreground font-semibold mb-2">{r.label}</p>
        <p className="text-2xl font-semibold tabular-nums text-foreground">{r.current}</p>
        <div className="flex items-center justify-between mt-2 pt-2 border-t border-border/50">
         <span className="text-3xs text-muted-foreground tabular-nums">vs. {r.previous}</span>
         <div className={`flex items-center gap-0.5 text-2xs font-semibold tabular-nums ${cls}`}>
          <Icon className="w-3 h-3" />
          {r.absolute
           ? `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(1)} pp`
           : `${r.delta >= 0 ? "+" : ""}${r.delta.toFixed(1)}%`}
         </div>
        </div>
       </div>
      );
     })}
    </div>
   </CardContent>
  </Card>
 );
}

const CHANNEL_META: Record<string, { label: string; icon: typeof Globe; cls: string }> = {
 widget: { label: "Widget web", icon: Globe, cls: "text-primary" },
 api: { label: "API directa", icon: Code, cls: "text-brand-teal" },
 playground: { label: "Previsualizar (interno)", icon: Play, cls: "text-warning" },
 unknown: { label: "Desconocido", icon: Circle, cls: "text-muted-foreground" },
};

function ChannelsPanel({ channels, loading }: { channels: ChannelStat[]; loading: boolean }) {
 return (
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between">
     <div>
      <CardTitle className="text-15">Canales de entrada</CardTitle>
      <CardDescription>De dónde llegan las conversaciones</CardDescription>
     </div>
     <Globe className="h-4 w-4 text-muted-foreground" />
    </div>
   </CardHeader>
   <CardContent>
    {loading ? (
     <div className="space-y-2">{[1,2,3].map(i => <Skeleton key={i} className="h-8 w-full" />)}</div>
    ) : channels.length === 0 ? (
     <EmptyState icon={Globe} title="Sin tráfico aún" description="Las conversaciones aparecerán clasificadas por canal" />
    ) : (
     <div className="space-y-2.5">
      {channels.map((c) => {
       const meta = CHANNEL_META[c.channel] ?? CHANNEL_META.unknown;
       const Icon = meta.icon;
       return (
        <div key={c.channel} className="flex items-center gap-3">
         <Icon className={`w-4 h-4 shrink-0 ${meta.cls}`} />
         <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
           <span className="text-13 font-medium">{meta.label}</span>
           <span className="text-2xs text-muted-foreground tabular-nums">{c.count} · {c.percentage.toFixed(1)}%</span>
          </div>
          <Progress value={c.percentage} className="h-1.5" />
         </div>
        </div>
       );
      })}
     </div>
    )}
   </CardContent>
  </Card>
 );
}

function CacheStatsPanel({ cache, loading }: { cache: CacheStats | null; loading: boolean }) {
 return (
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between">
     <div>
      <CardTitle className="text-15">Caché de respuestas</CardTitle>
      <CardDescription>{cache ? `Últimos ${cache.days} días` : "Respuestas reutilizadas frente a preguntas nuevas"}</CardDescription>
     </div>
     <Zap className="h-4 w-4 text-muted-foreground" />
    </div>
   </CardHeader>
   <CardContent>
    {loading ? (
     <div className="space-y-2">{[1,2].map(i => <Skeleton key={i} className="h-8 w-full" />)}</div>
    ) : !cache ? (
     <EmptyState icon={Zap} title="Sin datos" description="No hay información disponible" />
    ) : (cache.hits + cache.misses) === 0 ? (
     <EmptyState icon={Zap} title="Sin tráfico aún" description="No hay respuestas registradas en el período" />
    ) : (
     <>
      <div className="flex items-baseline gap-2 mb-3">
       <span className={`text-3xl font-bold tabular-nums ${
        cache.hit_rate >= 30 ? "text-success" : cache.hit_rate >= 10 ? "text-warning" : "text-muted-foreground"
       }`}>
        {cache.hit_rate.toFixed(1)}%
       </span>
       <span className="text-2xs text-muted-foreground">respuestas reutilizadas</span>
      </div>
      <div className="space-y-2">
       <div className="flex items-center justify-between text-xs">
        <span className="text-success font-medium">Reutilizadas</span>
        <span className="tabular-nums font-mono">{cache.hits}</span>
       </div>
       <Progress value={cache.hit_rate} className="h-1.5" indicatorClassName="bg-success" />
       <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground font-medium">Nuevas</span>
        <span className="tabular-nums font-mono">{cache.misses}</span>
       </div>
      </div>
     </>
    )}
   </CardContent>
  </Card>
 );
}

const feedbackChartConfig = {
 positive: { label: "Positivo", color: CHART_GREEN },
 negative: { label: "Negativo", color: "#EF4444" },
} satisfies ChartConfig;

function FeedbackPanel({ feedback, loading }: { feedback: AnalyticsFeedback | null; loading: boolean }) {
 const s = feedback?.summary;
 const trend = feedback?.trend ?? [];
 const hasData = (s?.total ?? 0) > 0;

 return (
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between">
     <div>
      <CardTitle className="text-15">Valoración de respuestas</CardTitle>
      <CardDescription>Valoraciones positivas y negativas de los mensajes del asistente</CardDescription>
     </div>
     <ThumbsUp className="h-4 w-4 text-muted-foreground" />
    </div>
   </CardHeader>
   <CardContent>
    {loading ? (
     <div className="space-y-3">
      <div className="flex gap-4">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-16 flex-1 rounded-xl" />)}</div>
      <Skeleton className="h-40 w-full" />
     </div>
    ) : !hasData ? (
     <EmptyState
      icon={ThumbsUp}
      title="Sin valoraciones aún"
      description="Cuando los usuarios valoren las respuestas del chatbot, las métricas aparecerán aquí"
     />
    ) : (
     <div className="space-y-6">
      {/* Summary row */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
       <div className="flex flex-col items-center justify-center gap-1 rounded-xl border border-border bg-muted/30 py-3">
        <span className="text-2xl font-bold tabular-nums">{s!.total}</span>
        <span className="text-2xs text-muted-foreground">Total valoraciones</span>
       </div>
       <div className="flex flex-col items-center justify-center gap-1 rounded-xl border border-success/30 bg-success/5 py-3">
        <span className="flex items-center gap-1 text-2xl font-bold tabular-nums text-success">
         <ThumbsUp className="w-4 h-4" />{s!.positive}
        </span>
        <span className="text-2xs text-muted-foreground">{s!.positive_rate.toFixed(1)}% positivas</span>
       </div>
       <div className="flex flex-col items-center justify-center gap-1 rounded-xl border border-destructive/30 bg-destructive/5 py-3">
        <span className="flex items-center gap-1 text-2xl font-bold tabular-nums text-destructive">
         <ThumbsDown className="w-4 h-4" />{s!.negative}
        </span>
        <span className="text-2xs text-muted-foreground">{(100 - s!.positive_rate).toFixed(1)}% negativas</span>
       </div>
      </div>

      {/* Positive rate bar */}
      <div className="space-y-1.5">
       <div className="flex justify-between text-2xs text-muted-foreground">
        <span>Tasa de satisfacción</span>
        <span className={`font-semibold ${s!.positive_rate >= 70 ? "text-success" : s!.positive_rate >= 50 ? "text-warning" : "text-destructive"}`}>
         {s!.positive_rate.toFixed(1)}%
        </span>
       </div>
       <div className="relative h-2 w-full rounded-full bg-muted overflow-hidden">
        <div
         className="absolute left-0 top-0 h-full rounded-full transition-all duration-700"
         style={{ width: `${s!.positive_rate}%`, background: CHART_GREEN }}
        />
       </div>
      </div>

      {/* Trend chart */}
      {trend.length > 1 && (
       <ChartContainer config={feedbackChartConfig} className="h-36 w-full">
        <AreaChart data={trend} margin={{ top: 4, right: 4, left: -24, bottom: 0 }}>
         <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" />
         <XAxis dataKey="date" tick={{ fontSize: 10 }} tickFormatter={(v: string) => v.slice(5)} />
         <YAxis tick={{ fontSize: 10 }} />
         <ChartTooltip content={<ChartTooltipContent />} />
         <Area type="monotone" dataKey="positive" stackId="1" stroke={CHART_GREEN} fill={CHART_GREEN} fillOpacity={0.3} />
         <Area type="monotone" dataKey="negative" stackId="1" stroke="#EF4444" fill="#EF4444" fillOpacity={0.3} />
        </AreaChart>
       </ChartContainer>
      )}
     </div>
    )}
   </CardContent>
  </Card>
 );
}


function PagesPanel({ pages, loading }: { pages: PageStat[]; loading: boolean }) {
 return (
  <Card>
   <CardHeader>
    <div className="flex items-center justify-between">
     <div>
      <CardTitle className="text-15">Páginas donde se abrió el chatbot</CardTitle>
      <CardDescription>Top páginas del sitio con más conversaciones iniciadas</CardDescription>
     </div>
     <MapPin className="h-4 w-4 text-muted-foreground" />
    </div>
   </CardHeader>
   <CardContent>
    {loading ? (
     <div className="space-y-2">{[1,2,3,4,5].map(i => <Skeleton key={i} className="h-8 w-full" />)}</div>
    ) : pages.length === 0 ? (
     <EmptyState
      icon={MapPin}
      title="Sin datos aún"
      description="Cuando el widget esté embebido en su sitio, aquí aparecerán las páginas con más conversaciones"
     />
    ) : (
     <div className="space-y-2.5">
      {pages.map((p) => {
       let displayLabel = p.page;
       try {
        const u = new URL(p.page);
        displayLabel = u.pathname === "/" ? u.hostname : `${u.hostname}${u.pathname}`;
       } catch { /* keep raw if not parseable */ }
       return (
        <div key={p.page} className="flex items-center gap-3">
         <Globe className="w-3.5 h-3.5 shrink-0 text-muted-foreground" />
         <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between mb-1">
           <span className="text-sm truncate max-w-[60%]" title={p.page}>{displayLabel}</span>
           <span className="text-2xs text-muted-foreground tabular-nums shrink-0">{p.count} · {p.percentage.toFixed(1)}%</span>
          </div>
          <Progress value={p.percentage} className="h-1.5" />
         </div>
        </div>
       );
      })}
     </div>
    )}
   </CardContent>
  </Card>
 );
}
