"use client";

import { forwardRef, useCallback, useEffect, useImperativeHandle, useMemo, useState } from "react";
import { AlertTriangle, Loader2, RefreshCw, CheckCircle, Cpu, HardDrive, Activity, History } from "lucide-react";

import api from "@/lib/api";
import { useApi } from "@/hooks/use-api";
import type { HealthDetailed, UptimeRow, HealthIncident, HealthSnapshotRow } from "@/types";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";
import { PeriodFilter } from "@/components/composed/period-filter";
import { Loading } from "@/components/ui/loading";
import { formatInProjectTz } from "@/lib/datetime";

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}


function fmtDuration(s: number | null): string {
  if (s == null) return "en curso";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  const h = Math.floor(m / 60);
  return `${h}h ${m % 60}m`;
}

function fmtRelative(iso: string | null): string {
  if (!iso) return "—";
  const ms = Date.now() - new Date(iso).getTime();
  const min = Math.floor(ms / 60_000);
  if (min < 1) return "hace un momento";
  if (min < 60) return `hace ${min} min`;
  const h = Math.floor(min / 60);
  if (h < 24) return `hace ${h}h`;
  const d = Math.floor(h / 24);
  return `hace ${d}d`;
}

const REFRESH_OPTIONS = [
  { value: 0, label: "Manual" },
  { value: 30, label: "30s" },
  { value: 60, label: "1m" },
  { value: 300, label: "5m" },
];


export interface SaludTabHandle {
  /** Toma una nueva muestra de salud y la registra en el historial, luego refresca todo. */
  check: () => Promise<void>;
  /** Solo recarga los datos ya existentes, sin registrar una muestra nueva. */
  refetchAll: () => Promise<void>;
  checking: boolean;
}

export const SaludTab = forwardRef<SaludTabHandle>(function SaludTab(_props, ref) {
  const [lastChecked, setLastChecked] = useState<Date | null>(null);
  const [autoRefreshSec, setAutoRefreshSec] = useState(0);
  const today = isoDay(new Date());
  const [dateFrom, setDateFrom] = useState(today);
  const [dateTo, setDateTo] = useState(today);
  const [checking, setChecking] = useState(false);

  const periodReady = !!dateFrom && !!dateTo && dateFrom <= dateTo;
  const periodQuery = `date_from=${dateFrom}&date_to=${dateTo}`;

  const { data: health, loading, refetch: refetchHealth } =
    useApi<HealthDetailed>("/health/detailed");
  const { data: uptimeData, refetch: refetchUptime } =
    useApi<UptimeRow[]>(periodReady ? `/health/uptime?${periodQuery}` : null);
  const { data: incidentsData, refetch: refetchIncidents } =
    useApi<HealthIncident[]>(periodReady ? `/health/incidents?${periodQuery}` : null);
  const { data: historyData, refetch: refetchHistory } =
    useApi<HealthSnapshotRow[]>("/health/history?hours=1");

  const uptime = uptimeData ?? [];
  const incidents = incidentsData ?? [];

  // Tomar el snapshot más reciente con datos de utilization
  const latestSnapshot = useMemo(() => {
    const withUtil = (historyData ?? []).filter((s) => s.cpu_percent != null).sort((a, b) =>
      new Date(b.recorded_at).getTime() - new Date(a.recorded_at).getTime()
    );
    return withUtil[0] ?? null;
  }, [historyData]);

  useEffect(() => {
    if (health) setLastChecked(new Date());
  }, [health]);

  const check = useCallback(async () => {
    setChecking(true);
    try {
      await api.post("/health/snapshot").catch(() => null);
      await Promise.all([refetchHealth(), refetchUptime(), refetchIncidents(), refetchHistory()]);
    } finally {
      setChecking(false);
    }
  }, [refetchHealth, refetchUptime, refetchIncidents, refetchHistory]);

  const refetchAll = useCallback(async () => {
    await Promise.all([refetchHealth(), refetchUptime(), refetchIncidents(), refetchHistory()]);
  }, [refetchHealth, refetchUptime, refetchIncidents, refetchHistory]);

  useImperativeHandle(ref, () => ({ check, refetchAll, checking }), [check, refetchAll, checking]);

  useEffect(() => {
    if (autoRefreshSec <= 0) return;
    const handle = setInterval(() => { void check(); }, autoRefreshSec * 1000);
    return () => clearInterval(handle);
  }, [autoRefreshSec, check]);


  if (loading && !health) {
    return <Loading />;
  }

  if (!health) {
    return <div className="text-center py-16 text-sm text-muted-foreground">No se pudo conectar al backend.</div>;
  }

  const degraded = health.services.filter((s) => s.status !== "ok");
  const allOk = degraded.length === 0;
  const uptimeByName = Object.fromEntries(uptime.map((u) => [u.service_name, u]));

  return (
    <div className="space-y-4">
      {/* Status banner + controles */}
      <div className={`flex items-center justify-between gap-3 px-4 py-3 rounded-xl border text-13 font-medium flex-wrap ${
        allOk
          ? "bg-brand-green/8 border-brand-green/30 text-brand-green"
          : "bg-warning/5 border-warning/30 text-warning"
      }`}>
        <div className="flex items-center gap-2">
          {allOk
            ? <CheckCircle className="w-4 h-4 shrink-0" />
            : <AlertTriangle className="w-4 h-4 shrink-0" />}
          <span>
            {allOk
              ? "Todos los servicios operativos"
              : `${degraded.length} servicio${degraded.length > 1 ? "s" : ""} con degradación. El chatbot sigue funcionando con fallback.`}
          </span>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {lastChecked && (
            <span className="text-2xs font-normal opacity-80">
              Actualizado {fmtRelative(lastChecked.toISOString())}
            </span>
          )}
          <select
            value={autoRefreshSec}
            onChange={(e) => setAutoRefreshSec(Number(e.target.value))}
            className="h-6 px-2 text-2xs border border-border bg-background rounded-md text-foreground"
            title="Auto-refresh"
          >
            {REFRESH_OPTIONS.map((o) => (
              <option key={o.value} value={o.value}>↻ {o.label}</option>
            ))}
          </select>
          <Button
            variant="outline"
            size="sm"
            onClick={() => void check()}
            disabled={checking}
            className={`h-6 gap-1.5 text-2xs px-2.5 ${
              allOk
                ? "border-brand-green/30 hover:bg-brand-green/10 text-brand-green"
                : "border-warning/30 hover:text-warning"
            }`}
          >
            {checking
              ? <Loader2 className="w-3 h-3 animate-spin" />
              : <RefreshCw className="w-3 h-3" />}
            Revisar
          </Button>
        </div>
      </div>

      {/* Services table — ahora con uptime y P50/P95/P99. El selector de
          rango de fechas vive aquí porque afecta tanto esta tabla (uptime/
          P50-P95-P99) como la de incidentes debajo. */}
      <Card className="overflow-hidden">
        <div className="px-5 py-3 border-b border-border">
          <PeriodFilter
            ariaLabel="Período de salud (uptime e incidentes)"
            dateFrom={dateFrom}
            dateTo={dateTo}
            onDateFromChange={setDateFrom}
            onDateToChange={setDateTo}
            maxDate={today}
          />
        </div>
        <div className="overflow-x-auto">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Servicio</TableHead>
              <TableHead className="w-24">Estado</TableHead>
              <TableHead className="w-20 text-right">Uptime</TableHead>
              <TableHead className="w-20 text-right hidden sm:table-cell">Resp. típica</TableHead>
              <TableHead className="w-20 text-right hidden sm:table-cell">95%</TableHead>
              <TableHead className="w-20 text-right hidden md:table-cell">99%</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {health.services.map((service) => {
              const ok = service.status === "ok";
              const u = uptimeByName[service.name];
              return (
                <TableRow key={service.name}>
                  <TableCell>
                    <div className="flex items-center gap-2.5">
                      <span className={`w-2 h-2 rounded-full shrink-0 ${ok ? "bg-brand-green" : "bg-destructive"}`} />
                      <span className="text-sm font-semibold text-foreground">{service.name}</span>
                    </div>
                    {service.detail && (
                      <p className="text-2xs text-muted-foreground mt-0.5 pl-4.5 truncate">{service.detail}</p>
                    )}
                  </TableCell>
                  <TableCell>
                    <span className={`inline-flex items-center gap-1.5 text-xs font-medium px-2 py-0.5 rounded-full ${
                      ok ? "bg-brand-green/10 text-brand-green" : "bg-destructive/10 text-destructive"
                    }`}>
                      {ok ? "Operativo" : service.status}
                    </span>
                  </TableCell>
                  <TableCell className="text-right">
                    {u ? (
                      <span className={`text-sm font-bold tabular-nums ${
                        u.uptime_pct >= 99 ? "text-brand-green" : u.uptime_pct >= 95 ? "text-warning" : "text-destructive"
                      }`}>
                        {u.uptime_pct.toFixed(1)}%
                      </span>
                    ) : <span className="text-sm text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-right text-sm tabular-nums hidden sm:table-cell">
                    {u?.p50_ms != null ? `${Math.round(u.p50_ms)}ms` : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-right text-sm tabular-nums hidden sm:table-cell">
                    {u?.p95_ms != null ? (
                      <span className={u.p95_ms > 500 ? "text-warning font-medium" : ""}>
                        {Math.round(u.p95_ms)}ms
                      </span>
                    ) : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                  <TableCell className="text-right text-sm tabular-nums hidden md:table-cell">
                    {u?.p99_ms != null ? (
                      <span className={u.p99_ms > 1000 ? "text-destructive font-medium" : ""}>
                        {Math.round(u.p99_ms)}ms
                      </span>
                    ) : <span className="text-muted-foreground">—</span>}
                  </TableCell>
                </TableRow>
              );
            })}
          </TableBody>
        </Table>
        </div>
        {uptime.length === 0 && (
          <div className="px-5 py-3 border-t border-border text-2xs text-muted-foreground bg-muted/20">
            Sin historial aún. Pulse <Activity className="inline w-3 h-3" /> Revisar para tomar una muestra ahora, o espere al siguiente ciclo automático.
          </div>
        )}
      </Card>

      {/* Resource utilization */}
      {latestSnapshot && (latestSnapshot.cpu_percent != null || latestSnapshot.mem_percent != null) && (
        <Card className="p-4">
          <div className="flex items-center gap-1.5 mb-3">
            <Cpu className="w-3.5 h-3.5 text-muted-foreground" />
            <h3 className="text-sm font-semibold">Recursos del servidor</h3>
            <span className="text-3xs text-muted-foreground">{fmtRelative(latestSnapshot.recorded_at)}</span>
          </div>
          <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
            <ResourceBar label="CPU" value={latestSnapshot.cpu_percent} icon={Cpu} />
            <ResourceBar label="Memoria" value={latestSnapshot.mem_percent} icon={Activity} />
            <ResourceBar label="Disco" value={latestSnapshot.disk_percent} icon={HardDrive} />
          </div>
        </Card>
      )}

      {/* Incidentes */}
      <Card className="overflow-hidden">
        <div className="px-5 py-3 border-b border-border bg-muted flex items-center justify-between">
          <div className="flex items-center gap-1.5">
            <History className="w-3.5 h-3.5 text-muted-foreground" />
            <h3 className="text-sm font-semibold">Historial de incidentes</h3>
          </div>
          <span className="text-2xs text-muted-foreground tabular-nums">
            {incidents.length} en {dateFrom} – {dateTo}
          </span>
        </div>
        {incidents.length === 0 ? (
          <EmptyState
            icon={CheckCircle}
            title="Sin incidentes"
            description="Sin incidentes en el periodo seleccionado."
            className="py-8"
          />
        ) : (
          <div className="overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Servicio</TableHead>
                <TableHead>Inicio</TableHead>
                <TableHead>Duración</TableHead>
                <TableHead>Muestras</TableHead>
                <TableHead>Último error</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {incidents.slice(0, 30).map((inc, i) => (
                <TableRow key={i}>
                  <TableCell className="font-medium">{inc.service_name}</TableCell>
                  <TableCell className="text-2xs text-muted-foreground tabular-nums">
                    {formatInProjectTz(inc.started_at, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                  </TableCell>
                  <TableCell className="text-xs">
                    <span className={inc.ended_at ? "text-muted-foreground" : "text-destructive font-medium"}>
                      {fmtDuration(inc.duration_seconds)}
                    </span>
                  </TableCell>
                  <TableCell className="text-xs tabular-nums text-muted-foreground">{inc.samples}</TableCell>
                  <TableCell className="text-2xs font-mono text-muted-foreground truncate max-w-md">
                    {inc.last_error ?? "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
          </div>
        )}
      </Card>

      {/* Compute info */}
      {health.compute && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-1 text-2xs text-muted-foreground px-1">
          <span>Versión: <span className="font-medium text-foreground">{health.version}</span></span>
          <span>Entorno: <span className="font-medium text-foreground">{health.environment}</span></span>
          <span>Cómputo: <span className={`font-medium ${health.compute.gpu_available ? "text-warning" : "text-foreground"}`}>
            {health.compute.gpu_available ? "GPU" : "CPU"}
          </span></span>
        </div>
      )}
    </div>
  );
});


function ResourceBar({ label, value, icon: Icon }: {
  label: string;
  value: number | null;
  icon: typeof Cpu;
}) {
  const pct = value ?? 0;
  const cls = pct >= 90 ? "bg-destructive" : pct >= 70 ? "bg-warning/50" : "bg-brand-green";
  const textCls = pct >= 90 ? "text-destructive" : pct >= 70 ? "text-warning" : "text-foreground";
  return (
    <div>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-1.5 text-2xs text-muted-foreground">
          <Icon className="w-3 h-3" />
          {label}
        </div>
        <span className={`text-sm font-bold tabular-nums ${textCls}`}>
          {value != null ? `${value.toFixed(1)}%` : "—"}
        </span>
      </div>
      <div className="h-1.5 bg-muted rounded-full overflow-hidden">
        <div className={`h-full ${cls} transition-all`} style={{ width: `${Math.min(100, pct)}%` }} />
      </div>
    </div>
  );
}
