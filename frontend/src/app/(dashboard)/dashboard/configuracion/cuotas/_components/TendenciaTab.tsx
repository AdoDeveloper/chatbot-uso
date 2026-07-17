"use client";

import { forwardRef, useImperativeHandle, useState } from "react";
import { BarChart3 } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PeriodFilter } from "@/components/composed/period-filter";
import { Loading } from "@/components/ui/loading";

interface UsagePoint { bucket: string; requests: number; throttles: number; }
interface UsageReport {
  hours: number; limit_per_min: number; limit_per_hour: number;
  total_requests: number; total_throttles: number; points: UsagePoint[];
}

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

function Stat({ label, value, accent }: { label: string; value: string | number; accent?: "amber" | "red" }) {
  const cls = accent === "red" ? "text-destructive" : accent === "amber" ? "text-warning" : "text-foreground";
  return (
    <div className="border border-border rounded-md px-3 py-2">
      <p className="text-3xs uppercase tracking-wider text-muted-foreground font-semibold">{label}</p>
      <p className={`text-lg font-bold tabular-nums ${cls}`}>{value}</p>
    </div>
  );
}

export interface TendenciaTabHandle {
  refetch: () => void;
}

export const TendenciaTab = forwardRef<TendenciaTabHandle>(function TendenciaTab(_props, ref) {
  const today = isoDay(new Date());
  const [dateFrom, setDateFrom] = useState(isoDay(new Date(Date.now() - 86400000)));
  const [dateTo, setDateTo] = useState(today);

  const periodReady = !!dateFrom && !!dateTo && dateFrom <= dateTo;
  const periodQuery = `date_from=${dateFrom}&date_to=${dateTo}`;

  const { data: report, loading, refetch } =
    useApi<UsageReport>(periodReady ? `/rate-limits/usage?${periodQuery}` : null);

  useImperativeHandle(ref, () => ({ refetch }));

  const maxRequests = Math.max(1, ...(report?.points.map((p) => p.requests) ?? [1]));
  const limitPerHour = report?.limit_per_hour ?? 0;
  const peakAlert = limitPerHour > 0 && maxRequests >= limitPerHour * 0.8;

  return (
    <div className="space-y-4">
      {loading ? (
        <Loading title="Uso vs. límite" />
      ) : (
      <Card>
        <CardHeader className="flex-row items-center justify-between flex-wrap gap-3">
          <div>
            <CardTitle className="text-15 font-semibold flex items-center gap-1.5">
              <BarChart3 className="w-4 h-4" /> Uso vs. límite
            </CardTitle>
            <p className="text-2xs text-muted-foreground mt-0.5">Peticiones de chat por hora vs. el techo configurado.</p>
          </div>
          <PeriodFilter
            ariaLabel="Período de tendencia"
            dateFrom={dateFrom}
            dateTo={dateTo}
            onDateFromChange={setDateFrom}
            onDateToChange={setDateTo}
            maxDate={today}
          />
        </CardHeader>
        <CardContent>
          {!report || report.points.length === 0 ? (
            <p className="text-sm text-muted-foreground py-8 text-center">Sin tráfico registrado en el periodo.</p>
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                <Stat label="Total requests" value={report.total_requests.toLocaleString()} />
                <Stat label="Throttles" value={report.total_throttles.toLocaleString()} accent={report.total_throttles > 0 ? "red" : undefined} />
                <Stat label="Pico horario" value={maxRequests.toLocaleString()} accent={peakAlert ? "amber" : undefined} />
                <Stat label="Límite/hora" value={limitPerHour.toLocaleString()} />
              </div>

              {peakAlert && (
                <div className="mb-3 px-3 py-2 rounded-md border border-warning/30 bg-warning/5 text-xs text-warning">
                  ⚠️ Pico {maxRequests} ≥ 80% del límite ({limitPerHour}/h). Considera subir el techo.
                </div>
              )}

              <div className="space-y-1">
                {report.points.slice().reverse().slice(0, 24).reverse().map((p) => {
                  const pct = Math.min(100, (p.requests / Math.max(maxRequests, 1)) * 100);
                  const overLimit = limitPerHour > 0 && p.requests >= limitPerHour;
                  const nearLimit = limitPerHour > 0 && p.requests >= limitPerHour * 0.8 && !overLimit;
                  const cls = overLimit ? "bg-destructive" : nearLimit ? "bg-warning/50" : "bg-primary/70";
                  const ts = new Date(p.bucket);
                  return (
                    <div key={p.bucket} className="flex items-center gap-2 text-2xs">
                      <span className="text-muted-foreground tabular-nums w-20 shrink-0">
                        {ts.toLocaleString("es", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                      </span>
                      <div className="flex-1 h-4 bg-muted rounded relative overflow-hidden">
                        <div className={`h-full ${cls} transition-all`} style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-foreground tabular-nums w-12 text-right shrink-0">{p.requests}</span>
                      {p.throttles > 0 && (
                        <span className="text-destructive tabular-nums w-10 text-right shrink-0">⛔{p.throttles}</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </>
          )}
        </CardContent>
      </Card>
      )}
    </div>
  );
});
