"use client";

import { forwardRef, useImperativeHandle, useState } from "react";
import { isoDay } from "@/lib/utils";
import { BarChart3 } from "lucide-react";
import { useApi } from "@/hooks/use-api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { PeriodFilter } from "@/components/composed/period-filter";
import { Loading } from "@/components/ui/loading";
import { EmptyState } from "@/components/ui/empty-state";

interface UsagePoint { bucket: string; requests: number; throttles: number; }
interface UsageReport {
  hours: number; limit_per_min: number; limit_per_hour: number;
  total_requests: number; total_throttles: number; points: UsagePoint[];
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
            <p className="text-2xs text-muted-foreground mt-0.5">
              Consultas de chat por hora en todo el sitio. El límite se aplica a cada IP por separado:
              los bloqueos muestran cuándo alguien lo alcanzó.
            </p>
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
            <EmptyState
              icon={BarChart3}
              title="Sin tráfico en el periodo"
              description="Seleccione otro rango de fechas para ver la tendencia."
            />
          ) : (
            <>
              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
                <Stat label="Consultas" value={report.total_requests.toLocaleString()} />
                <Stat label="Bloqueos por límite" value={report.total_throttles.toLocaleString()} accent={report.total_throttles > 0 ? "red" : undefined} />
                <Stat label="Hora con más consultas" value={maxRequests.toLocaleString()} />
                <Stat label="Límite por IP y hora" value={limitPerHour.toLocaleString()} />
              </div>

              <div className="space-y-1 max-h-96 overflow-y-auto pr-1">
                {report.points.map((p) => {
                  const pct = Math.min(100, (p.requests / Math.max(maxRequests, 1)) * 100);
                  const cls = p.throttles > 0 ? "bg-destructive" : "bg-primary/70";
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
                        <span className="text-destructive tabular-nums w-16 text-right shrink-0" title="Consultas bloqueadas por límite">
                          {p.throttles} bloq.
                        </span>
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
