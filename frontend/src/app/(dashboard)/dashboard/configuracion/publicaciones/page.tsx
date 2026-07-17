"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Rocket, CheckCircle2, AlertTriangle, Clock, FileText,
  Loader2, Settings2, CheckCheck, Ban, X,
  History, RotateCcw, Save, ChevronDown, ChevronRight,
  Eye, EyeOff, Settings, Cpu, Palette, Bell, Database,
  HelpCircle, Shield, Zap,
} from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useAuth } from "@/contexts/auth-context";
import { useToast } from "@/components/ui/toast";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/composed/stat-card";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { EmptyState } from "@/components/ui/empty-state";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Modal } from "@/components/composed/modal";
import { Alert, AlertTitle, AlertDescription } from "@/components/ui/alert";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { Source } from "@/types";
import { formatInProjectTz } from "@/lib/datetime";

interface DeployStatus {
  last_deployed_at: string | null;
  last_deployed_version: number | null;
  pending_sources: number;
  config_changed_since_deploy: boolean;
  never_deployed: boolean;
}

interface DeployResult {
  version: { id: string; version_number: number; description: string; created_at: string };
  pending_sources: number;
}

interface VersionOut {
  id: string;
  version_number: number;
  description: string;
  change_summary: string | null;
  trigger_source: string | null;
  snapshot_schema_version: number;
  is_active: boolean;
  created_by_name: string | null;
  created_at: string;
}

interface DiffChange {
  key?: string; id?: string; name?: string; action: string;
  old?: unknown; new?: unknown; changes?: Record<string, [unknown, unknown]>;
}
interface VersionDiff {
  version_number: number; change_summary: string | null;
  sections: Record<string, DiffChange[]>;
}

const TRIGGER_ICONS: Record<string, React.ElementType> = {
  settings: Settings, providers: Cpu, widget: Palette,
  escalation: Bell, notifications: Bell, sources: Database,
  faq: HelpCircle, guardrails: Shield, cache: Database,
  rate_limits: Zap, integrations: Settings, manual: History,
  rollback: RotateCcw, deploy: Rocket,
};

const TRIGGER_LABELS: Record<string, string> = {
  settings: "Configuración", providers: "Proveedores", widget: "Widget",
  escalation: "Escalamiento", notifications: "Notificaciones", sources: "Fuentes",
  faq: "FAQ", guardrails: "Guardrails", cache: "Cache", rate_limits: "Rate Limits",
  integrations: "Integraciones", manual: "Snapshot manual", rollback: "Rollback",
  deploy: "Publicación",
};

const SECTION_LABELS: Record<string, string> = {
  global_settings: "Configuración", llm_providers: "Proveedores LLM",
  widget_config: "Widget", escalation_rules: "Escalamiento",
  notification_rules: "Notificaciones",
  sources: "Fuentes", faq_entries: "FAQ",
};

function DiffSection({ section, changes }: { section: string; changes: DiffChange[] }) {
  if (!changes.length) return null;
  const isKV = section === "global_settings" || section === "widget_config";
  return (
    <div className="space-y-1.5">
      {isKV ? (
        <div className="rounded-lg border overflow-x-auto">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Campo</TableHead>
                <TableHead>Anterior</TableHead>
                <TableHead>Nuevo</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {changes.map((c, i) => (
                <TableRow key={i} className={c.action === "added" ? "bg-brand-green/10 hover:bg-brand-green/10" : c.action === "removed" ? "bg-destructive/5 hover:bg-destructive/5" : ""}>
                  <TableCell className="font-mono text-xs">{c.key}</TableCell>
                  <TableCell className="text-muted-foreground max-w-48 truncate">{c.old != null ? String(c.old).slice(0, 80) : "—"}</TableCell>
                  <TableCell className="max-w-48 truncate">{c.new != null ? String(c.new).slice(0, 80) : "—"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      ) : (
        <div className="space-y-1">
          {changes.map((c, i) => (
            <div key={i} className={`flex items-center gap-2 rounded-md px-3 py-1.5 text-sm ${
              c.action === "added" ? "bg-brand-green/10" :
              c.action === "removed" ? "bg-destructive/5 line-through text-muted-foreground" :
              "bg-warning/5"
            }`}>
              <Badge variant={c.action === "added" ? "success" : c.action === "removed" ? "destructive" : "warning"} className="text-3xs">
                {c.action === "added" ? "Nuevo" : c.action === "removed" ? "Eliminado" : "Modificado"}
              </Badge>
              <span className="font-medium">{c.name || c.id?.slice(0, 8)}</span>
              {c.action === "modified" && c.changes && (
                <span className="text-2xs text-muted-foreground ml-auto">
                  {Object.keys(c.changes).slice(0, 3).join(", ")}
                </span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PendingSourcesList({
  sources, reviewing, onApprove, onReject,
}: {
  sources: Source[];
  reviewing: string | null;
  onApprove: (s: Source) => void;
  onReject: (s: Source) => void;
}) {
  const [showAll, setShowAll] = useState(false);
  const visible = showAll ? sources : sources.slice(0, 3);
  const hidden = sources.length - visible.length;
  return (
    <div className="ml-11">
      <div className={`space-y-1.5 ${showAll ? "max-h-96 overflow-y-auto pr-1" : ""}`}>
        {visible.map((s) => (
          <div key={s.id} className="flex items-center gap-3 px-3 py-2 rounded-lg bg-muted/30 border border-border/50">
            <FileText className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
            <div className="min-w-0 flex-1">
              <p className="truncate text-xs font-medium">{s.name}</p>
              <p className="text-3xs text-muted-foreground tabular-nums">
                {s.type.toUpperCase()} · {s.chunk_count ?? 0} fragmentos
              </p>
            </div>
            <div className="flex items-center gap-1.5 shrink-0">
              <Button size="sm" variant="outline" onClick={() => onApprove(s)} disabled={reviewing === s.id}
                className="h-6 px-2 text-2xs gap-1 border-success/40 text-success hover:bg-success/10 hover:border-success/60">
                {reviewing === s.id ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCheck className="w-3 h-3" />}
                Aprobar
              </Button>
              <Button size="sm" variant="outline" onClick={() => onReject(s)} disabled={reviewing === s.id}
                className="h-6 px-2 text-2xs gap-1 border-destructive/40 text-destructive hover:bg-destructive/10">
                <Ban className="w-3 h-3" /> Rechazar
              </Button>
            </div>
          </div>
        ))}
      </div>
      {hidden > 0 && (
        <Button type="button" variant="link" size="xs" onClick={() => setShowAll(true)} className="mt-2 px-0">
          Ver {hidden} fuente{hidden === 1 ? "" : "s"} más
        </Button>
      )}
      {showAll && sources.length > 3 && (
        <Button type="button" variant="link" size="xs" onClick={() => setShowAll(false)} className="mt-2 px-0 text-muted-foreground">
          Mostrar menos
        </Button>
      )}
    </div>
  );
}

export default function PublicacionesPage() {
  const { user } = useAuth();
  const { toast, confirm } = useToast();
  const canDeploy = !!user;

  const [, setRefreshing] = useState(false);
  const [deploying, setDeploying] = useState(false);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [rejectTarget, setRejectTarget] = useState<{ source: Source; reason: string } | null>(null);

  const [snapshotOpen, setSnapshotOpen] = useState(false);
  const [snapshotDesc, setSnapshotDesc] = useState("");
  const [saving, setSaving] = useState(false);

  const [showAllSnapshots, setShowAllSnapshots] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [diff, setDiff] = useState<VersionDiff | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [rollbackTarget, setRollbackTarget] = useState<VersionOut | null>(null);
  const [rolling, setRolling] = useState(false);
  const [rollbackWarnings, setRollbackWarnings] = useState<string[]>([]);

  const { data: status, loading: loadingStatus, error: statusError, refetch: refetchStatus } =
    useApi<DeployStatus>("/versions/deploy/status");
  const { data: sourcesData, loading: loadingSources, error: sourcesError, refetch: refetchSources, setData: setSources } =
    useApi<Source[]>("/sources");
  const { data: versionsData, loading: loadingVersions, error: versionsError, refetch: refetchVersions } =
    useApi<{ versions: VersionOut[] }>("/versions?page_size=50");

  const pendingSources = useMemo(
    () => (sourcesData ?? []).filter((s) => s.status === "ready" && s.review_status === "pendiente_revision"),
    [sourcesData],
  );
  const versions = versionsData?.versions ?? [];
  const loading = loadingStatus || loadingSources || loadingVersions;

  const loadError = statusError || sourcesError || versionsError;
  useEffect(() => {
    if (loadError) toast({ type: "error", message: "No se pudo cargar el estado de publicaciones." });
  }, [loadError, toast]);

  async function load() {
    setRefreshing(true);
    try {
      await Promise.all([refetchStatus(), refetchSources(), refetchVersions()]);
      toast({ type: "success", message: "Publicaciones actualizadas.", duration: 2000 });
    } finally {
      setRefreshing(false);
    }
  }

  async function handleApprove(s: Source) {
    setReviewing(s.id);
    try {
      await api.post(`/sources/${s.id}/approve`);
      setSources((prev) => prev
        ? prev.map((x) => (x.id === s.id ? { ...x, review_status: "aprobada" as Source["review_status"] } : x))
        : prev);
      toast({ type: "success", message: `"${s.name}" aprobada.` });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo aprobar la fuente.") });
    } finally { setReviewing(null); }
  }

  async function handleReject() {
    if (!rejectTarget?.reason.trim()) return;
    const { source, reason } = rejectTarget;
    setReviewing(source.id);
    try {
      await api.post(`/sources/${source.id}/reject`, { reason });
      setSources((prev) => prev
        ? prev.map((x) => (x.id === source.id ? { ...x, review_status: "rechazada" as Source["review_status"] } : x))
        : prev);
      setRejectTarget(null);
      toast({ type: "success", message: `"${source.name}" rechazada.` });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo rechazar la fuente.") });
    } finally { setReviewing(null); }
  }

  const handleDeploy = async () => {
    const ok = await confirm({
      title: "¿Publicar a producción?",
      message: `Se publicará la configuración actual como la nueva versión de producción.${status?.pending_sources ? ` Hay ${status.pending_sources} fuente(s) pendientes que no estarán disponibles hasta ser aprobadas.` : ""}`,
      confirmText: "Publicar",
    });
    if (!ok) return;

    setDeploying(true);
    try {
      const { data } = await api.post<DeployResult>("/versions/deploy", {
        description: "Publicación a producción",
      });
      toast({ type: "success", message: `Versión v${data.version.version_number} publicada correctamente.` });
      load();
    } catch (err: unknown) {
      const httpStatus = (err as { response?: { status?: number } })?.response?.status;
      if (httpStatus === 409) {
        toast({ type: "info", message: "La producción ya está al día. No hay cambios que publicar." });
        load();
      } else if (httpStatus === 403) {
        toast({ type: "error", message: "No tiene permisos para publicar." });
      } else {
        toast({ type: "error", message: getErrorMessage(err, "No se pudo publicar. Intente nuevamente.") });
      }
    } finally { setDeploying(false); }
  };

  async function handleSaveSnapshot() {
    setSaving(true);
    try {
      await api.post("/versions", { description: snapshotDesc || "Punto de restauración manual" });
      toast({ type: "success", message: "Punto de restauración guardado." });
      setSnapshotOpen(false);
      setSnapshotDesc("");
      load();
    } catch (err: unknown) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar el snapshot.") });
    } finally { setSaving(false); }
  }

  async function handleExpand(v: VersionOut) {
    if (expandedId === v.id) { setExpandedId(null); setDiff(null); return; }
    setExpandedId(v.id);
    setDiffLoading(true);
    try {
      const { data } = await api.get<VersionDiff>(`/versions/${v.id}/diff`);
      setDiff(data);
    } catch (err) {
      setDiff(null);
      toast({ type: "error", message: getErrorMessage(err, "No se pudo cargar el diff de esta versión.") });
    } finally { setDiffLoading(false); }
  }

  async function handleRollback() {
    if (!rollbackTarget) return;
    setRolling(true);
    try {
      const { data } = await api.post<{ version: VersionOut; warnings: string[] }>(`/versions/${rollbackTarget.id}/rollback`);
      setRollbackWarnings(data.warnings);
      if (!data.warnings.length) {
        setRollbackTarget(null);
        toast({ type: "success", message: `Restaurado a v${rollbackTarget.version_number}.` });
      } else {
        toast({ type: "warning", message: `Restaurado con ${data.warnings.length} advertencia(s).` });
      }
      load();
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al restaurar la versión.") });
    } finally { setRolling(false); }
  }

  const lastDeployedAt = status?.last_deployed_at
    ? formatInProjectTz(status.last_deployed_at, { dateStyle: "medium", timeStyle: "short" })
    : null;

  const neverDeployed = !!status?.never_deployed;
  const hasConfigChanges = !!status?.config_changed_since_deploy;
  const hasPendingSources = pendingSources.length > 0;

  const latestDeployId = versions.find((v) => v.is_active)?.id;
  const displayed = showAllSnapshots ? versions : versions.filter((v) => v.trigger_source === "deploy");
  const activeSections = diff ? Object.entries(diff.sections).filter(([, changes]) => changes.length > 0) : [];

  return (
    <div className="space-y-6">
      <PageHeader
        icon={Rocket}
        title="Publicaciones"
        tip={
          <>
            Revise los cambios en borrador, apruebe fuentes y publique a producción. El widget
            siempre usa la última versión publicada; la vista previa refleja la configuración
            actual en tiempo real. Puede restaurar cualquier versión anterior sin perder los
            cambios pendientes.
          </>
        }
      />

      {/* Never-deployed warning — widget is using draft settings */}
      {!loading && neverDeployed && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle className="text-sm font-semibold">
            Sin versión publicada
          </AlertTitle>
          <AlertDescription className="text-xs mt-1">
            El chatbot está usando la configuración actual sin revisión previa.{" "}
            <strong>Publica la primera versión</strong> para estabilizar el entorno de producción
            y controlar qué cambios llegan al widget.
          </AlertDescription>
        </Alert>
      )}

      {/* Stat cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
        <StatCard
          title="Última publicación"
          value={lastDeployedAt ?? "Nunca publicado"}
          description={status?.last_deployed_version ? `v${status.last_deployed_version}` : undefined}
          loading={loading}
          compact
        />

        <StatCard
          title="Estado"
          value={neverDeployed ? "Sin publicar" : hasConfigChanges ? "Cambios pendientes" : "Publicado"}
          valueIcon={neverDeployed || hasConfigChanges ? AlertTriangle : CheckCircle2}
          accent={neverDeployed || hasConfigChanges ? "amber" : "green"}
          loading={loading}
        />

        <StatCard
          title="Fuentes pendientes"
          value={hasPendingSources ? `${pendingSources.length} por revisar` : "Sin pendientes"}
          valueIcon={hasPendingSources ? Clock : CheckCircle2}
          accent={hasPendingSources ? "amber" : "green"}
          loading={loading}
        />
      </div>

      {/* Pre-flight */}
      <Card>
        <CardHeader className="pb-4 border-b">
          <CardTitle className="text-15 font-semibold">Validación previa</CardTitle>
          <p className="text-2xs text-muted-foreground mt-0.5">Revise y apruebe los cambios antes de publicar a producción.</p>
        </CardHeader>

        {/* Config row */}
        <div className="px-5 py-3 border-b border-border/60">
          <div className="flex items-center gap-3">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${hasConfigChanges ? "bg-warning/10" : "bg-success/10"}`}>
              <Settings2 className={`w-4 h-4 ${hasConfigChanges ? "text-warning" : "text-success"}`} />
            </div>
            <div className="flex-1 min-w-0">
              <p className="text-13 font-medium">Configuración</p>
              {loading ? <Skeleton className="h-3 w-52 mt-1.5" /> : (
                <p className="text-2xs text-muted-foreground mt-0.5">
                  {neverDeployed
                    ? "Primera publicación — se publicará la configuración inicial del chatbot."
                    : hasConfigChanges
                      ? "Hay cambios sin publicar en ajustes del asistente, widget o proveedores LLM."
                      : "Sin cambios desde la última publicación."}
                </p>
              )}
            </div>
            {!loading && (
              <span className={`text-3xs px-2 py-0.5 rounded-full font-medium border shrink-0 ${hasConfigChanges ? "bg-warning/10 text-warning border-warning/30" : "bg-success/10 text-success border-success/30"}`}>
                {neverDeployed ? "Primera vez" : hasConfigChanges ? "Pendiente" : "Publicado"}
              </span>
            )}
          </div>
        </div>

        {/* Sources row */}
        <div className="px-5 py-3 border-b border-border/60">
          <div className="flex items-center gap-3 mb-3">
            <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${hasPendingSources ? "bg-warning/10" : "bg-success/10"}`}>
              <FileText className={`w-4 h-4 ${hasPendingSources ? "text-warning" : "text-success"}`} />
            </div>
            <div className="flex-1">
              <p className="text-13 font-medium">Fuentes de conocimiento</p>
              {loading ? <Skeleton className="h-3 w-48 mt-1.5" /> : (
                <p className="text-2xs text-muted-foreground mt-0.5">
                  {hasPendingSources
                    ? `${pendingSources.length} fuente(s) procesadas, pendientes de aprobación.`
                    : "Todas las fuentes están aprobadas."}
                </p>
              )}
            </div>
            {!loading && (
              <span className={`text-3xs px-2 py-0.5 rounded-full font-medium border shrink-0 ${hasPendingSources ? "bg-warning/10 text-warning border-warning/30" : "bg-success/10 text-success border-success/30"}`}>
                {hasPendingSources ? `${pendingSources.length} pendiente${pendingSources.length > 1 ? "s" : ""}` : "Al día"}
              </span>
            )}
          </div>
          {loading ? (
            <div className="space-y-2 ml-11">{[1, 2].map((i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
          ) : hasPendingSources && (
            <PendingSourcesList
              sources={pendingSources}
              reviewing={reviewing}
              onApprove={handleApprove}
              onReject={(s) => setRejectTarget({ source: s, reason: "" })}
            />
          )}
        </div>

      </Card>

      {/* Publish action */}
      <Card>
        <CardHeader className="pb-4 border-b">
          <CardTitle className="text-15 font-semibold">Publicar versión</CardTitle>
          <p className="text-2xs text-muted-foreground mt-0.5">
            El widget activo usará esta versión. La vista previa refleja los cambios en tiempo real.
          </p>
        </CardHeader>
        <CardContent className="pt-5">
          {loading ? (
            <Skeleton className="h-9 w-32" />
          ) : !hasConfigChanges && !neverDeployed ? (
            <div className="flex items-center justify-between gap-4 flex-wrap">
              <div className="flex items-center gap-2 text-sm text-success">
                <CheckCircle2 className="w-4 h-4 shrink-0" />
                Producción al día — sin cambios pendientes
              </div>
              <Button variant="ghost" size="xs" onClick={() => setSnapshotOpen(true)} className="text-muted-foreground shrink-0">
                <Save /> Guardar punto de restauración
              </Button>
            </div>
          ) : (
            <div className="space-y-4">
              {hasPendingSources && (
                <div className="flex items-center gap-2 rounded-lg border border-warning/20 bg-warning/5 px-3.5 py-2.5 text-xs text-warning">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
                  {pendingSources.length} fuente(s) aún pendientes de aprobación — no estarán disponibles en producción hasta ser aprobadas arriba
                </div>
              )}
              <div className="flex items-center gap-3 flex-wrap">
                <Button onClick={handleDeploy} disabled={deploying || !canDeploy} className="gap-1.5">
                  {deploying ? <Loader2 className="w-4 h-4 animate-spin" /> : <Rocket className="w-4 h-4" />}
                  {deploying ? "Publicando..." : "Publicar a producción"}
                </Button>
                <Button variant="ghost" size="xs" onClick={() => setSnapshotOpen(true)} className="text-muted-foreground">
                  <Save /> Guardar punto de restauración
                </Button>
                {!canDeploy && (
                  <p className="text-2xs text-muted-foreground">Debe iniciar sesión para publicar.</p>
                )}
              </div>
            </div>
          )}
        </CardContent>
      </Card>

      {/* History */}
      <div>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-base font-semibold flex items-center gap-2">
            <History className="w-4 h-4 text-muted-foreground" />
            Historial
          </h2>
          <Button
            variant="outline"
            size="sm"
            onClick={() => setShowAllSnapshots((v) => !v)}
            className="shrink-0"
          >
            {showAllSnapshots ? <EyeOff /> : <Eye />}
            {showAllSnapshots ? "Solo publicaciones" : "Ver todos los snapshots"}
          </Button>
        </div>

        {showAllSnapshots && (
          <div className="mb-3 flex items-center gap-2 rounded-lg border border-muted bg-muted/30 px-4 py-2.5 text-2xs text-muted-foreground">
            <Eye className="w-3.5 h-3.5 shrink-0" />
            Mostrando todos los snapshots: publicaciones, manuales y rollbacks.
          </div>
        )}

        {loading ? (
          <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-16 w-full" />)}</div>
        ) : displayed.length === 0 ? (
          <Card>
            <CardContent>
              <EmptyState
                icon={Rocket}
                title="Sin publicaciones"
                description="Cuando publiques la configuración por primera vez, aparecerá aquí."
              />
            </CardContent>
          </Card>
        ) : (
          <div className="space-y-2">
            {displayed.map((v) => {
              const TriggerIcon = TRIGGER_ICONS[v.trigger_source || "manual"] || Settings;
              const isExpanded = expandedId === v.id;
              const isInProduction = v.id === latestDeployId;
              const isDeploy = v.trigger_source === "deploy";
              const isRollback = v.trigger_source === "rollback";
              const isManual = v.trigger_source === "manual";

              return (
                <Card key={v.id} className={`overflow-hidden ${isInProduction ? "border-primary/30 bg-primary/2" : isManual || isRollback ? "border-dashed opacity-75" : ""}`}>
                  <button onClick={() => handleExpand(v)} className="w-full text-left px-5 py-3 flex items-center gap-3 hover:bg-muted/30 transition-colors">
                    <div className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full ${
                      isInProduction ? "bg-primary text-primary-foreground" :
                      isDeploy ? "bg-primary/10 text-primary" :
                      isRollback ? "bg-warning/10 text-warning" :
                      "bg-muted/50 text-muted-foreground"
                    }`}>
                      <TriggerIcon className="h-3.5 w-3.5" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <span className="font-semibold text-13">v{v.version_number}</span>
                        {isInProduction && <Badge className="text-3xs">En producción</Badge>}
                        {v.trigger_source && (
                          <Badge variant={isDeploy ? "outline" : "secondary"} className="text-3xs">
                            {TRIGGER_LABELS[v.trigger_source] || v.trigger_source}
                          </Badge>
                        )}
                      </div>
                      <p className="text-13 text-muted-foreground truncate mt-0.5">{v.change_summary || v.description}</p>
                      <p className="text-2xs text-muted-foreground/60 mt-0.5">
                        {formatInProjectTz(v.created_at, { day: "2-digit", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" })}
                        {v.created_by_name && ` · ${v.created_by_name}`}
                      </p>
                    </div>
                    <div className="flex items-center gap-2 shrink-0">
                      {isDeploy && !isInProduction && (
                        <Button variant="outline" size="sm" onClick={(e) => { e.stopPropagation(); setRollbackTarget(v); }} className="gap-1 text-2xs h-7">
                          <RotateCcw className="h-3 w-3" /> Restaurar
                        </Button>
                      )}
                      {isExpanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                    </div>
                  </button>

                  {isExpanded && (
                    <div className="border-t px-5 py-3">
                      {diffLoading ? (
                        <div className="space-y-2">{[1, 2].map((i) => <Skeleton key={i} className="h-10 w-full" />)}</div>
                      ) : !diff || activeSections.length === 0 ? (
                        <p className="text-13 text-muted-foreground text-center py-3">
                          {v.snapshot_schema_version < 2 ? "Versión antigua — solo configuración básica" : "Sin cambios detectados"}
                        </p>
                      ) : activeSections.length === 1 ? (
                        <div>
                          <h4 className="text-xs font-medium text-muted-foreground uppercase mb-2">{SECTION_LABELS[activeSections[0][0]] || activeSections[0][0]}</h4>
                          <DiffSection section={activeSections[0][0]} changes={activeSections[0][1]} />
                        </div>
                      ) : (
                        <Tabs defaultValue={activeSections[0][0]}>
                          <TabsList className="mb-3">
                            {activeSections.map(([section, changes]) => (
                              <TabsTrigger key={section} value={section} className="gap-1 text-xs">
                                {SECTION_LABELS[section] || section}
                                <Badge variant="secondary" className="ml-1 h-4 text-3xs">{changes.length}</Badge>
                              </TabsTrigger>
                            ))}
                          </TabsList>
                          {activeSections.map(([section, changes]) => (
                            <TabsContent key={section} value={section}>
                              <DiffSection section={section} changes={changes} />
                            </TabsContent>
                          ))}
                        </Tabs>
                      )}
                    </div>
                  )}
                </Card>
              );
            })}
          </div>
        )}
      </div>

      {/* Reject modal */}
      <Modal
        open={!!rejectTarget}
        onClose={() => setRejectTarget(null)}
        size="md"
        title={
          <span className="flex items-center gap-2">
            <Ban className="w-4 h-4 text-destructive" />
            Rechazar fuente
          </span>
        }
        subtitle={rejectTarget?.source.name ? `“${rejectTarget.source.name}”` : undefined}
        footer={
          <>
            <Button variant="outline" size="sm" onClick={() => setRejectTarget(null)}>
              Cancelar
            </Button>
            <Button variant="destructive" size="sm" className="gap-1.5" onClick={handleReject}
              disabled={!rejectTarget?.reason.trim() || (reviewing === rejectTarget?.source.id)}>
              {reviewing === rejectTarget?.source.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Ban className="w-3.5 h-3.5" />}
              Rechazar
            </Button>
          </>
        }
      >
        <div className="space-y-4 pt-1">
          <label className="block text-xs font-medium text-muted-foreground mb-1.5">Motivo</label>
          <Input
            value={rejectTarget?.reason ?? ""}
            onChange={(e) => setRejectTarget((p) => p ? { ...p, reason: e.target.value } : p)}
            placeholder="Indica por qué se rechaza esta fuente..."
            onKeyDown={(e) => e.key === "Enter" && handleReject()}
            autoFocus
          />
        </div>
      </Modal>

      {/* Snapshot dialog */}
      <Modal
        open={snapshotOpen}
        onClose={() => setSnapshotOpen(false)}
        title="Guardar punto de restauración"
        subtitle="Guarde el estado actual como punto de restauración. No afecta la versión activa en el widget."
        footer={
          <>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setSnapshotOpen(false)}>
              <X className="h-3.5 w-3.5" /> Cancelar
            </Button>
            <Button size="sm" className="gap-1.5" onClick={handleSaveSnapshot} disabled={saving}>
              {saving ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Save className="h-3.5 w-3.5" />}
              {saving ? "Guardando..." : "Guardar"}
            </Button>
          </>
        }
      >
        <div className="space-y-2">
          <Label>Descripción <span className="text-muted-foreground font-normal">(opcional)</span></Label>
          <Input
            value={snapshotDesc}
            onChange={(e) => setSnapshotDesc(e.target.value)}
            placeholder="Ej: Antes de cambiar el prompt principal"
            onKeyDown={(e) => e.key === "Enter" && !saving && handleSaveSnapshot()}
          />
        </div>
      </Modal>

      {/* Rollback dialog */}
      <Modal
        open={!!rollbackTarget}
        onClose={() => { setRollbackTarget(null); setRollbackWarnings([]); }}
        title={rollbackTarget ? `Restaurar a v${rollbackTarget.version_number}` : "Restaurar"}
        subtitle="El widget activo usará la configuración de esta versión. La vista previa no se modifica. Proveedores sin API key quedarán desactivados."
        footer={
          <>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => { setRollbackTarget(null); setRollbackWarnings([]); }}>
              <X className="h-3.5 w-3.5" /> Cancelar
            </Button>
            <Button size="sm" className="gap-1.5" onClick={handleRollback} disabled={rolling}>
              {rolling ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
              {rolling ? "Restaurando..." : "Restaurar"}
            </Button>
          </>
        }
      >
        {rollbackWarnings.length > 0 && (
          <Alert variant="warning">
            <AlertTitle>Advertencias</AlertTitle>
            <AlertDescription>
              <ul className="list-disc pl-4 text-sm space-y-1">{rollbackWarnings.map((w, i) => <li key={i}>{w}</li>)}</ul>
            </AlertDescription>
          </Alert>
        )}
      </Modal>
    </div>
  );
}
