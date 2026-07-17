"use client";

import { useState } from "react";
import { KeyRound, Ban, ShieldAlert, ShieldCheck, Shield, AlertTriangle, LockOpen, Loader2 } from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { StatCard } from "@/components/composed/stat-card";
import { HelpTip } from "@/components/ui/help-tip";
import { PeriodFilter } from "@/components/composed/period-filter";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { formatInProjectTz } from "@/lib/datetime";

interface SecuritySummary {
  days: number;
  failed_logins: number;
  failed_logins_prev: number;
  distinct_ips_failing: number;
  injections_blocked: number;
  injections_blocked_prev: number;
  throttled_ips_now: number;
  admin_actions: number;
}
interface FailedLoginGroup { ip: string | null; attempts: number; distinct_emails: number; last_attempt_at: string }
interface InjectionByCategory { category: string; count: number; sample_label: string | null }
interface InjectionSample { id: string; ip: string | null; pattern: string | null; question_preview: string | null; created_at: string }
interface ThrottledIP { ip: string; current_count: number; limit: number; window: string; ttl_seconds: number }

function fmtDelta(now: number, prev: number): { text: string; cls: string } | null {
  if (prev === 0 && now === 0) return null;
  if (prev === 0) return { text: `+${now}`, cls: "text-destructive" };
  const pct = Math.round(((now - prev) / prev) * 100);
  if (pct === 0) return { text: "sin cambio", cls: "text-muted-foreground" };
  return {
    text: `${pct > 0 ? "+" : ""}${pct}% vs periodo previo`,
    cls: pct > 0 ? "text-destructive" : "text-brand-green",
  };
}

function isoDay(d: Date): string {
  return d.toISOString().slice(0, 10);
}

export function SeguridadTab() {
  const { toast } = useToast();
  const today = isoDay(new Date());
  const [dateFrom, setDateFrom] = useState(isoDay(new Date(Date.now() - 6 * 86400000)));
  const [dateTo, setDateTo] = useState(today);
  const [unblocking, setUnblocking] = useState<string | null>(null);

  const periodReady = !!dateFrom && !!dateTo && dateFrom <= dateTo;
  const periodQuery = `date_from=${dateFrom}&date_to=${dateTo}`;

  const { data: summary, loading: l1, error: e1, setData: setSummary } =
    useApi<SecuritySummary>(periodReady ? `/security/summary?${periodQuery}` : null);
  const { data: loginsData, loading: l2, error: e2 } =
    useApi<FailedLoginGroup[]>(periodReady ? `/security/login-failures?${periodQuery}` : null);
  const { data: categoriesData, loading: l3, error: e3 } =
    useApi<InjectionByCategory[]>(periodReady ? `/security/injections/by-category?${periodQuery}` : null);
  const { data: samplesData, loading: l4, error: e4 } =
    useApi<InjectionSample[]>(periodReady ? `/security/injections/samples?${periodQuery}&limit=15` : null);
  const { data: throttledData, setData: setThrottled } =
    useApi<ThrottledIP[]>("/rate-limits/throttled");

  const logins = loginsData ?? [];
  const categories = categoriesData ?? [];
  const samples = samplesData ?? [];
  const throttled = throttledData ?? [];
  const loading = l1 || l2 || l3 || l4;
  const fetchError = (e1 || e2 || e3 || e4)
    ? "No se pudo cargar el resumen de seguridad. Inténtelo de nuevo más tarde."
    : null;

  async function handleUnblock(ip: string) {
    setUnblocking(ip);
    try {
      await api.delete(`/rate-limits/reset/${encodeURIComponent(ip)}`);
      setThrottled((prev) => (prev ?? []).filter((t) => t.ip !== ip));
      setSummary((s) => s ? { ...s, throttled_ips_now: Math.max(0, s.throttled_ips_now - 1) } : s);
      toast({ type: "success", message: `IP ${ip} desbloqueada.` });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo desbloquear la IP.") });
    } finally {
      setUnblocking(null);
    }
  }

  const loginsDelta = summary ? fmtDelta(summary.failed_logins, summary.failed_logins_prev) : null;
  const injDelta = summary ? fmtDelta(summary.injections_blocked, summary.injections_blocked_prev) : null;
  const maxCatCount = Math.max(1, ...categories.map((c) => c.count));

  const [ipFilter, setIpFilter] = useState<string | null>(null);
  const filteredSamples = ipFilter ? samples.filter((s) => s.ip === ipFilter) : samples;

  return (
    <div className="space-y-6">
      {fetchError && (
        <div className="flex items-start gap-2.5 px-4 py-3 rounded-xl border border-destructive/30 bg-destructive/5 text-13 text-destructive">
          <AlertTriangle className="w-4 h-4 shrink-0 mt-0.5" />
          <span>{fetchError}</span>
        </div>
      )}
      <div className="flex items-center justify-end">
        <PeriodFilter
          ariaLabel="Período de seguridad"
          dateFrom={dateFrom}
          dateTo={dateTo}
          onDateFromChange={setDateFrom}
          onDateToChange={setDateTo}
          maxDate={today}
        />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Intentos fallidos"
          value={summary?.failed_logins ?? 0}
          icon={KeyRound}
          accent="red"
          description={loginsDelta?.text}
          tip="Logins rechazados en la ventana seleccionada. Un pico súbito o muchos distintos emails desde una IP puede indicar fuerza bruta."
          loading={loading}
        />
        <StatCard
          title="IPs únicas fallando"
          value={summary?.distinct_ips_failing ?? 0}
          icon={Ban}
          accent="amber"
          tip="Direcciones IP distintas con al menos un intento fallido. Alto = posible ataque distribuido."
          loading={loading}
        />
        <StatCard
          title="Mensajes bloqueados"
          value={summary?.injections_blocked ?? 0}
          icon={ShieldAlert}
          accent="primary"
          description={injDelta?.text}
          tip="Mensajes del chatbot que coincidieron con un patrón de contenido no permitido y fueron bloqueados antes de generar una respuesta."
          loading={loading}
        />
        <StatCard
          title="Usuarios con límite activo"
          value={summary?.throttled_ips_now ?? 0}
          icon={Shield}
          loading={loading}
        />
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-15">Mensajes bloqueados por categoría</CardTitle>
            <CardDescription>Distribución de los tipos de contenido que más se están bloqueando</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
            ) : categories.length === 0 ? (
              <EmptyState icon={ShieldCheck} title="Sin bloqueos" description="Ningún mensaje bloqueado en el periodo." />
            ) : (
              <div className="space-y-2.5">
                {categories.map((c) => (
                  <div key={c.category}>
                    <div className="flex items-center justify-between text-sm mb-1">
                      <div className="min-w-0">
                        <span className="font-medium">{c.category}</span>
                        {c.sample_label && <span className="text-2xs text-muted-foreground ml-1.5">· {c.sample_label}</span>}
                      </div>
                      <Badge variant="secondary" className="tabular-nums">{c.count}</Badge>
                    </div>
                    <div className="h-1.5 bg-muted rounded-full overflow-hidden">
                      <div
                        className={`h-full rounded-full transition-all ${c.category === "Otro / desconocido" ? "bg-muted-foreground/30" : "bg-primary"}`}
                        style={{ width: `${(c.count / maxCatCount) * 100}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-15">Logins fallidos por IP</CardTitle>
            <CardDescription>IPs con más intentos rechazados</CardDescription>
          </CardHeader>
          <CardContent>
            {loading ? (
              <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
            ) : logins.length === 0 ? (
              <EmptyState icon={ShieldCheck} title="Sin intentos fallidos" description="Todos los logins fueron exitosos en el periodo." />
            ) : (
              <div className="space-y-2">
                {logins.map((g) => {
                  const isThrottled = g.ip != null && throttled.some((t) => t.ip === g.ip);
                  const throttleInfo = g.ip != null ? throttled.find((t) => t.ip === g.ip) : null;
                  return (
                    <div key={g.ip ?? "null"} className={`flex items-center justify-between rounded-lg border bg-card px-3 py-2 ${isThrottled ? "border-destructive/40 bg-destructive/5" : "border-border"}`}>
                      <div className="flex items-center gap-2 min-w-0">
                        <Ban className={`w-3.5 h-3.5 shrink-0 ${isThrottled ? "text-destructive" : "text-muted-foreground"}`} />
                        <code className="text-2xs font-mono truncate">{g.ip ?? "—"}</code>
                        <span className="text-2xs text-muted-foreground">
                          · {g.distinct_emails} email{g.distinct_emails === 1 ? "" : "s"}
                        </span>
                        {isThrottled && (
                          <Badge className="text-3xs bg-destructive/10 text-destructive border-destructive/30">
                            con límite · expira en {throttleInfo?.ttl_seconds}s
                          </Badge>
                        )}
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <Badge variant="destructive" className="tabular-nums">{g.attempts}</Badge>
                        <span className="text-3xs tabular-nums text-muted-foreground">
                          {formatInProjectTz(g.last_attempt_at, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                        </span>
                        {isThrottled && g.ip && (
                          <Button
                            size="sm"
                            variant="outline"
                            className="h-7 px-2 text-2xs gap-1 border-destructive/30 text-destructive hover:bg-destructive/10"
                            disabled={unblocking === g.ip}
                            onClick={() => handleUnblock(g.ip!)}
                          >
                            {unblocking === g.ip
                              ? <Loader2 className="w-3 h-3 animate-spin" />
                              : <LockOpen className="w-3 h-3" />}
                            Liberar
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Throttled IPs panel */}
      {throttled.length > 0 && (
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <div>
                <CardTitle className="text-15">Usuarios con límite activo</CardTitle>
                <CardDescription>Conexiones con restricción de velocidad activa</CardDescription>
              </div>
              <Badge variant="destructive" className="tabular-nums">{throttled.length}</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <div className="space-y-2">
              {throttled.map((t) => (
                <div key={t.ip} className="flex items-center justify-between rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2">
                  <div className="flex items-center gap-2 min-w-0">
                    <Shield className="w-3.5 h-3.5 text-destructive shrink-0" />
                    <code className="text-2xs font-mono">{t.ip}</code>
                    <span className="text-2xs text-muted-foreground">
                      {t.current_count}/{t.limit} solicitudes
                    </span>
                  </div>
                  <div className="flex items-center gap-2 shrink-0">
                    <span className="text-2xs tabular-nums text-muted-foreground">expira en {t.ttl_seconds < 60 ? `${t.ttl_seconds}s` : `${Math.floor(t.ttl_seconds / 60)}m`}</span>
                    <Button
                      size="sm"
                      variant="outline"
                      className="h-7 px-2 text-2xs gap-1 border-destructive/30 text-destructive hover:bg-destructive/10"
                      disabled={unblocking === t.ip}
                      onClick={() => handleUnblock(t.ip)}
                    >
                      {unblocking === t.ip
                        ? <Loader2 className="w-3 h-3 animate-spin" />
                        : <LockOpen className="w-3 h-3" />}
                      Unbloquear
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader>
          <div className="flex items-start justify-between gap-3 flex-wrap">
            <div>
              <CardTitle className="text-15">Mensajes bloqueados recientes</CardTitle>
              <CardDescription>Mensaje que se intentó enviar, motivo del bloqueo y origen</CardDescription>
            </div>
            {ipFilter && (
              <div className="flex items-center gap-1.5">
                <Badge variant="outline" className="font-mono text-3xs gap-1">
                  <span className="text-muted-foreground">IP:</span> {ipFilter}
                </Badge>
                <button
                  type="button"
                  onClick={() => setIpFilter(null)}
                  className="text-2xs text-primary hover:underline"
                >
                  Quitar filtro
                </button>
              </div>
            )}
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}</div>
          ) : filteredSamples.length === 0 ? (
            <EmptyState icon={ShieldCheck} title={ipFilter ? `Sin mensajes bloqueados de ${ipFilter}` : "Sin bloqueos recientes"} description="No hubo mensajes bloqueados en el periodo." />
          ) : (
            <div className="space-y-2">
              {filteredSamples.map((s) => (
                <div key={s.id} className="rounded-lg border border-border bg-card p-3 space-y-1.5">
                  <div className="flex items-start justify-between gap-2">
                    <p className="text-13 flex-1 italic">&ldquo;{s.question_preview ?? "(sin texto)"}&rdquo;</p>
                    <span className="text-3xs tabular-nums text-muted-foreground shrink-0">
                      {formatInProjectTz(s.created_at, { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" })}
                    </span>
                  </div>
                  <div className="flex items-center gap-2 text-2xs">
                    {s.ip ? (
                      <button
                        type="button"
                        title="Filtrar por esta IP"
                        onClick={() => setIpFilter(s.ip === ipFilter ? null : s.ip)}
                        className={`inline-flex items-center px-1.5 py-0.5 rounded border font-mono text-2xs transition-colors ${
                          s.ip === ipFilter
                            ? "border-primary/40 bg-primary/10 text-primary"
                            : "border-border bg-muted hover:border-primary/40 hover:bg-primary/5"
                        }`}
                      >
                        {s.ip}
                      </button>
                    ) : (
                      <Badge variant="outline" className="font-mono">—</Badge>
                    )}
                    {s.pattern && <Badge variant="secondary" className="font-mono text-3xs max-w-sm truncate">{s.pattern}</Badge>}
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
