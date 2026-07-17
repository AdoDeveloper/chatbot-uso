"use client";

import { forwardRef, useEffect, useImperativeHandle, useState } from "react";
import { Activity, Unlock, Loader2, Save } from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { useToast } from "@/components/ui/toast";
import { Loading } from "@/components/ui/loading";

interface RateLimitConfig { chat_per_min: number; chat_per_hour: number; }
interface ThrottledIP { ip: string; current_count: number; limit: number; window: string; ttl_seconds: number; }

export interface LimitesTabHandle {
  refetch: () => void;
}

export const LimitesTab = forwardRef<LimitesTabHandle>(function LimitesTab(_props, ref) {
  const { toast, confirm } = useToast();
  const { data: config, loading: loadingConfig, error: configError, refetch: refetchConfig, setData: setConfig } =
    useApi<RateLimitConfig>("/rate-limits/config");
  const { data: throttledData, loading: loadingThrottled, error: throttledError, refetch: refetchThrottled, setData: setThrottled } =
    useApi<ThrottledIP[]>("/rate-limits/throttled");
  const throttled = throttledData ?? [];
  const loading = loadingConfig || loadingThrottled;
  const [saving, setSaving] = useState(false);

  function load() {
    refetchConfig();
    refetchThrottled();
  }

  useImperativeHandle(ref, () => ({ refetch: load }));

  const loadError = configError || throttledError;
  useEffect(() => {
    if (loadError) toast({ type: "error", message: "No se pudieron cargar las cuotas." });
  }, [loadError, toast]);

  async function saveConfig() {
    if (!config) return;
    setSaving(true);
    try {
      await api.patch("/rate-limits/config", config);
      toast({ type: "success", message: "Configuración guardada." });
    } catch (err) { toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar la configuración.") }); }
    finally { setSaving(false); }
  }

  async function unblockIp(ip: string) {
    const ok = await confirm({
      title: `¿Desbloquear ${ip}?`,
      message: "La IP podrá volver a hacer peticiones inmediatamente.",
      confirmText: "Desbloquear",
    });
    if (!ok) return;
    try {
      await api.delete(`/rate-limits/reset/${ip}`);
      setThrottled((prev) => (prev ?? []).filter((t) => t.ip !== ip));
      toast({ type: "success", message: `${ip} desbloqueada.` });
    } catch (err) { toast({ type: "error", message: getErrorMessage(err, "No se pudo desbloquear la IP.") }); }
  }

  if (loading || !config) {
    return <Loading />;
  }

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-15 font-semibold">Límites configurados</CardTitle>
        </CardHeader>
        <CardContent className="space-y-4">
          <div>
            <label className="text-xs font-medium block mb-1">Chat por minuto / IP</label>
            <Input type="number" value={config.chat_per_min}
              onChange={(e) => setConfig({ ...config, chat_per_min: Number(e.target.value) })}
              className="max-w-32" />
          </div>
          <div>
            <label className="text-xs font-medium block mb-1">Chat por hora / IP</label>
            <Input type="number" value={config.chat_per_hour}
              onChange={(e) => setConfig({ ...config, chat_per_hour: Number(e.target.value) })}
              className="max-w-32" />
          </div>
          <Button onClick={saveConfig} disabled={saving} size="sm" className="gap-1.5">
            {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            {saving ? "Guardando…" : "Guardar"}
          </Button>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-15 font-semibold">Usuarios con límite activo</CardTitle>
        </CardHeader>
        <CardContent>
          {throttled.length === 0 ? (
            <EmptyState icon={Activity} title="Sin usuarios con límite"
              description="Ningún usuario está siendo limitado en este momento." className="py-8" />
          ) : (
            <div className="divide-y">
              {throttled.map((t) => (
                <div key={t.ip} className="flex items-center justify-between py-2.5">
                  <div>
                    <p className="text-sm font-mono font-semibold">{t.ip}</p>
                    <p className="text-2xs text-muted-foreground">
                      {t.current_count}/{t.limit} solicitudes · expira en {t.ttl_seconds < 60 ? `${t.ttl_seconds}s` : `${Math.floor(t.ttl_seconds / 60)}m`}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="outline" className="text-destructive border-destructive/40">Throttle</Badge>
                    <Button variant="ghost" size="sm" onClick={() => unblockIp(t.ip)} className="gap-1.5">
                      <Unlock className="w-3.5 h-3.5" /> Desbloquear
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
});
