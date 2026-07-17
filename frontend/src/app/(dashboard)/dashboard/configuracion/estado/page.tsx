"use client";

import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from "react";
import { HeartPulse, Wrench, Loader2, Trash2, BarChart2, Database, Save, Bell, Activity } from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { PageHeader } from "@/components/ui/page-header";
import { SaludTab, type SaludTabHandle } from "../_components/SaludTab";
import { LimitesTab, type LimitesTabHandle } from "../cuotas/_components/LimitesTab";
import { TendenciaTab, type TendenciaTabHandle } from "../cuotas/_components/TendenciaTab";

interface SyncResult {
  qdrant_chunks_total: number;
  valid_source_ids: number;
  orphan_chunks_deleted: number;
  cache_invalidated_count: number;
}

interface CacheStatsOut {
  total_entries: number;
  enabled: boolean;
  ttl_seconds: number;
  similarity_threshold: number;
}

interface CacheConfigCardHandle {
  refetch: () => Promise<void>;
}

const CacheConfigCard = forwardRef<CacheConfigCardHandle>(function CacheConfigCard(_props, ref) {
  const { toast } = useToast();
  const { data, loading, refetch } = useApi<CacheStatsOut>("/cache/stats");
  const [enabled, setEnabled] = useState(true);
  const [ttlHours, setTtlHours] = useState(12);
  const [threshold, setThreshold] = useState(0.9);
  const [saving, setSaving] = useState(false);

  useImperativeHandle(ref, () => ({ refetch }), [refetch]);

  useEffect(() => {
    if (!data) return;
    setEnabled(data.enabled);
    setTtlHours(Math.max(1, Math.round(data.ttl_seconds / 3600)));
    setThreshold(data.similarity_threshold);
  }, [data]);

  async function save() {
    setSaving(true);
    try {
      await api.patch("/cache/config", {
        enabled,
        ttl_seconds: ttlHours * 3600,
        similarity_threshold: threshold,
      });
      toast({ type: "success", message: "Configuración del caché guardada." });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar la configuración del caché.") });
    } finally {
      setSaving(false);
    }
  }

  if (loading) return <Card className="p-5 animate-pulse h-40" />;

  return (
    <Card className="p-5">
      <div className="flex items-start gap-3 mb-4">
        <div className="p-2 rounded-lg bg-primary/10 text-primary shrink-0">
          <Database className="w-4 h-4" />
        </div>
        <div className="min-w-0 flex-1">
          <h3 className="text-15 font-semibold">Caché de respuestas</h3>
          <p className="text-2xs text-muted-foreground mt-0.5">
            Reutiliza respuestas de preguntas similares para responder al instante.
            {data ? ` Entradas actuales: ${data.total_entries}.` : ""}
          </p>
        </div>
        <Switch checked={enabled} onCheckedChange={setEnabled} aria-label="Activar caché" />
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-4">
        <div>
          <label htmlFor="cache-ttl" className="text-2xs font-medium block mb-1">
            Vigencia de las respuestas (horas)
          </label>
          <Input
            id="cache-ttl"
            type="number"
            min={1}
            max={168}
            value={ttlHours}
            onChange={(e) => setTtlHours(Number(e.target.value))}
            disabled={!enabled}
          />
        </div>
        <div>
          <label htmlFor="cache-threshold" className="text-2xs font-medium block mb-1">
            Umbral de similitud (0.5 a 0.99)
          </label>
          <Input
            id="cache-threshold"
            type="number"
            min={0.5}
            max={0.99}
            step={0.01}
            value={threshold}
            onChange={(e) => setThreshold(Number(e.target.value))}
            disabled={!enabled}
          />
        </div>
      </div>

      <Button size="sm" onClick={save} disabled={saving} className="gap-1.5">
        {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
        {saving ? "Guardando..." : "Guardar"}
      </Button>
    </Card>
  );
});

function EstadoContent() {
  const { confirm, toast } = useToast();
  const [syncing, setSyncing] = useState(false);
  const [clearing, setClearing] = useState(false);
  const [purgingHealth, setPurgingHealth] = useState(false);
  const saludRef = useRef<SaludTabHandle>(null);
  const cacheRef = useRef<CacheConfigCardHandle>(null);

  async function syncQdrant() {
    const ok = await confirm({
      title: "¿Sincronizar Qdrant con la base de datos?",
      message:
        "Buscará fragmentos en el índice cuya fuente ya no existe en la base de datos y los eliminará. " +
        "También invalidará el caché. Útil cuando el chatbot devuelve respuestas con info de documentos eliminados.",
      confirmText: "Sincronizar",
    });
    if (!ok) return;
    setSyncing(true);
    try {
      const { data } = await api.post<SyncResult>("/maintenance/sync-qdrant");
      toast({
        type: "success",
        message: `${data.orphan_chunks_deleted} chunks huérfanos eliminados.`,
      });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo sincronizar Qdrant.") });
    } finally {
      setSyncing(false);
    }
  }

  async function purgeHealthOutliers() {
    const ok = await confirm({
      title: "¿Limpiar historial de salud?",
      message:
        "Elimina mediciones con latencia > 2s que distorsionan los percentiles P95/P99. " +
        "Son datos del arranque inicial o caídas severas que ya no son representativos.",
      confirmText: "Limpiar historial",
      variant: "danger",
    });
    if (!ok) return;
    setPurgingHealth(true);
    try {
      const { data } = await api.delete<{ deleted: number; threshold_ms: number }>(
        "/maintenance/health-snapshots/outliers"
      );
      toast({ type: "success", message: `${data.deleted} mediciones anómalas eliminadas.` });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo limpiar el historial.") });
    } finally {
      setPurgingHealth(false);
    }
  }

  async function clearCache() {
    const ok = await confirm({
      title: "¿Limpiar todo el caché?",
      message:
        "Borra el caché semántico (respuestas guardadas por similitud) y el caché exacto (Redis). " +
        "Las próximas consultas serán más lentas porque irán al modelo, pero garantiza que no haya respuestas viejas.",
      confirmText: "Limpiar caché",
      variant: "danger",
    });
    if (!ok) return;
    setClearing(true);
    try {
      const { data } = await api.delete<{ deleted: number }>("/cache/clear");
      toast({ type: "success", message: `${data.deleted} entradas de caché eliminadas.` });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo limpiar el caché.") });
    } finally {
      setClearing(false);
    }
  }

  return (
    <div>
      <div className="flex items-center mb-6">
        <h2 className="text-base font-semibold flex-1 min-w-0 truncate">Salud de los servicios</h2>
      </div>

      <section className="mb-10">
        <SaludTab ref={saludRef} />
      </section>

      <section className="mb-10">
        <h2 className="text-base font-semibold mb-3">Caché</h2>
        <CacheConfigCard ref={cacheRef} />
      </section>

      <section>
        <div className="mb-3">
          <h2 className="text-base font-semibold">Recovery</h2>
          <p className="text-2xs text-muted-foreground mt-0.5">
            <strong>No es necesario ejecutarlas en uso normal</strong>: al eliminar
            un documento, los fragmentos del índice y el caché ya se limpian
            automáticamente. Use estas herramientas solo si sospecha
            desincronización.
          </p>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          <Card className="p-5">
            <div className="flex items-start gap-3 mb-3">
              <div className="p-2 rounded-lg bg-warning/15 text-warning shrink-0">
                <Wrench className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-15 font-semibold">Sincronizar Qdrant ↔ BD</h3>
                <p className="text-2xs text-muted-foreground mt-0.5">
                  Detecta chunks en el índice vectorial cuyo documento original ya
                  no existe en la base de datos y los elimina.
                </p>
              </div>
            </div>
            <Button size="sm" variant="outline" onClick={syncQdrant} disabled={syncing} className="gap-1.5 w-full">
              {syncing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Wrench className="w-3.5 h-3.5" />}
              Sincronizar ahora
            </Button>
          </Card>

          <Card className="p-5">
            <div className="flex items-start gap-3 mb-3">
              <div className="p-2 rounded-lg bg-destructive/15 text-destructive shrink-0">
                <Trash2 className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-15 font-semibold">Limpiar caché completo</h3>
                <p className="text-2xs text-muted-foreground mt-0.5">
                  Borra cache semántico + cache exacto. Próximas consultas serán
                  lentas pero garantiza respuestas frescas.
                </p>
              </div>
            </div>
            <Button size="sm" variant="outline" onClick={clearCache} disabled={clearing} className="gap-1.5 w-full text-destructive">
              {clearing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Trash2 className="w-3.5 h-3.5" />}
              Limpiar caché
            </Button>
          </Card>

          <Card className="p-5">
            <div className="flex items-start gap-3 mb-3">
              <div className="p-2 rounded-lg bg-warning/15 text-warning shrink-0">
                <BarChart2 className="w-4 h-4" />
              </div>
              <div className="min-w-0 flex-1">
                <h3 className="text-15 font-semibold">Limpiar historial de salud</h3>
                <p className="text-2xs text-muted-foreground mt-0.5">
                  Elimina mediciones con latencia &gt; 2s que distorsionan los
                  percentiles P95/P99 (datos del arranque inicial o caídas severas).
                </p>
              </div>
            </div>
            <Button size="sm" variant="outline" onClick={purgeHealthOutliers} disabled={purgingHealth} className="gap-1.5 w-full text-warning">
              {purgingHealth ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <BarChart2 className="w-3.5 h-3.5" />}
              Limpiar P99
            </Button>
          </Card>
        </div>
      </section>
    </div>
  );
}

function CuotasContent() {
  const limitesRef = useRef<LimitesTabHandle>(null);
  const tendenciaRef = useRef<TendenciaTabHandle>(null);
  const [tab, setTab] = useState("config");

  return (
    <div>
      <div className="flex items-center mb-4">
        <h2 className="text-base font-semibold flex-1 min-w-0 truncate">Cuotas de uso</h2>
      </div>
      <Tabs value={tab} onValueChange={(v) => setTab(v)}>
        <TabsList className="mb-6">
          <TabsTrigger value="config">Límites</TabsTrigger>
          <TabsTrigger value="tendencia">Tendencia</TabsTrigger>
        </TabsList>
        <TabsContent value="config"><LimitesTab ref={limitesRef} /></TabsContent>
        <TabsContent value="tendencia"><TendenciaTab ref={tendenciaRef} /></TabsContent>
      </Tabs>
    </div>
  );
}

export default function EstadoPage() {
  return (
    <div>
      <PageHeader icon={HeartPulse} title="Estado del sistema" tip="Salud de los servicios, historial de incidentes, notificaciones y cuotas de uso del sistema." />

      <Tabs defaultValue="estado">
        <TabsList className="mb-6">
          <TabsTrigger value="estado"><HeartPulse /> Estado</TabsTrigger>
          <TabsTrigger value="cuotas"><Activity /> Cuotas</TabsTrigger>
        </TabsList>

        <TabsContent value="estado"><EstadoContent /></TabsContent>
        <TabsContent value="cuotas"><CuotasContent /></TabsContent>
      </Tabs>
    </div>
  );
}
