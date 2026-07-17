"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useApi } from "@/hooks/use-api";
import type { AnalyticsDashboard, LLMProvider, Source, ChatConversationOut, HealthDetailed } from "@/types";
import {
 MessageSquare, Clock, TrendingUp, Users,
 Cpu, ArrowUpRight, Database,
    CheckCircle2, ShieldAlert, ShieldCheck,
   Upload, Play, AlertTriangle,
     KeyRound, UserRound, Inbox,
   ChevronRight,
} from "lucide-react";

import { useAuth } from "@/contexts/auth-context";
import { usePermission } from "@/hooks/use-permission";
import { PERM } from "@/lib/permissions";
import { useToast } from "@/components/ui/toast";
import { OnboardingWizard } from "@/components/composed/onboarding-wizard";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { Button } from "@/components/ui/button";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/composed/stat-card";


interface SecuritySummary {
 days: number;
 failed_logins: number;
 injections_blocked: number;
 throttled_ips_now: number;
 distinct_ips_failing: number;
}


export default function DashboardPage() {
  const { toast } = useToast();
  const { user } = useAuth();
  const can = usePermission();
  const isAdmin = can(PERM.SYSTEM_MANAGE);

 const { data: metrics, loading: loadingMetrics, error: metricsError } =
   useApi<AnalyticsDashboard>("/analytics/dashboard");
 const { data: sourcesData, loading: loadingSources, error: sourcesError } =
   useApi<Source[]>("/sources");
 const { data: escalationsData, loading: loadingEscalations, error: escalationsError } =
   useApi<{ items: ChatConversationOut[] }>("/conversations?status=escalated&page_size=4");
 // Sección admin — solo se consulta con el permiso adecuado (path null la pospone)
 const { data: providersData, loading: loadingProviders } =
   useApi<LLMProvider[]>(isAdmin ? "/providers" : null, [isAdmin]);
 const { data: security, loading: loadingSecurity } =
   useApi<SecuritySummary>(isAdmin ? "/security/summary?days=7" : null, [isAdmin]);
 const { data: health, loading: loadingHealth } =
   useApi<HealthDetailed>(isAdmin ? "/health/detailed" : null, [isAdmin]);
 const { data: deployStatus, loading: loadingDeploy } =
  useApi<{
   last_deployed_at: string | null;
   pending_sources: number;
   config_changed_since_deploy: boolean;
   never_deployed: boolean;
  }>(isAdmin ? "/versions/deploy/status" : null, [isAdmin]);

 const providers = providersData ?? [];
 const sources = sourcesData ?? [];
 const escalations = escalationsData?.items ?? [];
 // Granular loading per section — each reveals independently as its calls settle
 const loadingContent = loadingSources || loadingEscalations;
 const loadingAdmin = loadingProviders || loadingSecurity || loadingHealth || loadingDeploy;

 useEffect(() => {
  if (metricsError) toast({ type: "error", message: "No se pudieron cargar las métricas." });
 }, [metricsError, toast]);
 useEffect(() => {
  if (sourcesError) toast({ type: "error", message: "Algunos datos no pudieron cargarse." });
 }, [sourcesError, toast]);
 useEffect(() => {
  if (escalationsError) toast({ type: "error", message: "No se pudieron cargar los escalamientos pendientes." });
 }, [escalationsError, toast]);

 const activeProviders = providers.filter((p) => p.is_active && p.priority !== null);
 const recentSources = sources.slice(0, 5);
 const today = new Date().toLocaleDateString("es", { weekday: "long", day: "numeric", month: "long" });

 return (
  <div>
   {/* Wizard de bienvenida — solo visible si el sistema no está completamente
       configurado y el admin no ha hecho dismiss. Carga su estado del backend. */}
   <OnboardingWizard />

   <PageHeader
    title={`Hola, ${user?.full_name?.split(" ")[0] ?? "Administrador"}`}
    tip={`Resumen del sistema · ${today}`}
   />

   {/* KPIs */}
   <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4 mb-6">
    <StatCard title="Consultas hoy" value={metrics ? String(metrics.queries_today) : "—"} delta={metrics?.queries_today_delta} deltaLabel="vs. ayer" icon={MessageSquare} loading={loadingMetrics} />
    <StatCard title="Tasa de resolución" value={metrics ? `${metrics.resolution_rate}%` : "—"} delta={metrics?.resolution_rate_delta} deltaLabel="vs. semana anterior" icon={TrendingUp} loading={loadingMetrics} />
    <StatCard title="Sesiones hoy" value={metrics ? String(metrics.unique_users_today) : "—"} icon={Users} loading={loadingMetrics} />
    <StatCard title="Latencia promedio" value={metrics ? `${(metrics.avg_latency_ms / 1000).toFixed(1)}s` : "—"} delta={metrics?.avg_latency_delta} deltaLabel="vs. semana anterior" icon={Clock} loading={loadingMetrics} />
   </div>

   {/* Banner de salud: solo si hay servicios degradados */}
   {can(PERM.SYSTEM_MANAGE) && health && health.services.some((s) => s.status === "error" || s.status === "down") && (
    <div className="mb-6 px-4 py-3 rounded-xl border border-destructive/30 bg-destructive/5 text-destructive flex items-center gap-3">
     <AlertTriangle className="w-4 h-4 shrink-0" />
     <p className="text-sm">
      <span className="font-semibold">Servicio degradado:</span>{" "}
      {health.services.filter((s) => s.status === "error" || s.status === "down").map((s) => s.name).join(", ")}
     </p>
     <Link href="/dashboard/configuracion/estado" className="ml-auto text-xs hover:underline shrink-0">
      Ver detalle →
     </Link>
    </div>
   )}

   {/* Ciclo de trabajo: documentos → pruebas → publicación */}
   {can(PERM.SYSTEM_MANAGE) && (
    <WorkflowCycle
     providers={providers}
     deployStatus={deployStatus}
     loading={loadingContent || loadingAdmin}
    />
   )}

   {/* Quick actions strip */}
   {can(PERM.KNOWLEDGE_UPDATE) && (
    <div className="grid grid-cols-1 sm:grid-cols-4 gap-3 mb-6">
     <QuickAction href="/dashboard/conocimiento/documentos" icon={Upload} label="Subir fuente" hint="Añade a la base de conocimiento" />
     <QuickAction href="/dashboard/conversaciones" icon={MessageSquare} label="Conversaciones" hint="Revisar chats recientes" />
     <QuickAction href="/dashboard/conversaciones/escalamientos" icon={Inbox} label="Escalamientos" hint="Bandeja de casos por atender" />
     <QuickAction href="/dashboard/configuracion/playground" icon={Play} label="Previsualizar" hint="Chat de prueba en vivo" />
    </div>
   )}



   {/* Security + health snapshot row */}
   {can(PERM.SYSTEM_MANAGE) && (
    <div className="grid grid-cols-1 sm:grid-cols-2 gap-4 mb-6">
     {/* Security snapshot — 1 col (admin only) */}
     <Card>
      <CardHeader className="flex-row items-center justify-between pb-4 border-b">
       <div>
         <CardTitle className="text-15 font-semibold">Seguridad</CardTitle>
         <p className="text-2xs text-muted-foreground mt-0.5">Últimos 7 días</p>
       </div>
       <Link href="/dashboard/actividad/seguridad">
        <Button variant="ghost" size="sm" className="text-2xs text-muted-foreground h-7">Ver detalle</Button>
       </Link>
      </CardHeader>
      <CardContent className="pt-4 space-y-2.5">
       {loadingAdmin ? (
        <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-8 w-full" />)}</div>
       ) : !security ? (
        <p className="text-13 text-muted-foreground">No disponible</p>
       ) : (
        <>
         <SecurityRow
          icon={KeyRound}
          label="Logins fallidos"
          value={security.failed_logins}
          bad={security.failed_logins > 0}
         />
         <SecurityRow
          icon={ShieldAlert}
          label="Inyecciones bloqueadas"
          value={security.injections_blocked}
          bad={security.injections_blocked > 5}
         />
         <SecurityRow
          icon={AlertTriangle}
          label="Usuarios con límite activo"
          value={security.throttled_ips_now}
          bad={security.throttled_ips_now > 0}
         />
         {security.failed_logins === 0 && security.injections_blocked === 0 && security.throttled_ips_now === 0 && (
          <div className="flex items-center gap-2 text-2xs text-success pt-1">
           <ShieldCheck className="w-3.5 h-3.5" />
           Sin incidentes relevantes
          </div>
         )}
        </>
       )}
      </CardContent>
      </Card>

     {/* Salud de servicios — semáforo simple */}
     <Card>
      <CardHeader className="flex-row items-center justify-between pb-4 border-b">
       <div>
         <CardTitle className="text-15 font-semibold">Salud</CardTitle>
         <p className="text-2xs text-muted-foreground mt-0.5">Estado de servicios</p>
       </div>
       <Link href="/dashboard/configuracion/estado">
        <Button variant="ghost" size="sm" className="text-2xs text-muted-foreground h-7">Ver detalle</Button>
       </Link>
      </CardHeader>
      <CardContent className="pt-4 space-y-2">
       {loadingAdmin ? (
        <div className="space-y-2">{[1, 2, 3].map((i) => <Skeleton key={i} className="h-6 w-full" />)}</div>
       ) : !health ? (
         <p className="text-2xs text-muted-foreground">No disponible</p>
        ) : (
        health.services.slice(0, 5).map((s) => {
         const ok = s.status === "ok" || s.status === "healthy";
         const warn = s.status === "degraded" || s.status === "warning";
         const cls = ok ? "bg-success" : warn ? "bg-warning" : "bg-destructive";
         return (
          <div key={s.name} className="flex items-center justify-between gap-2 text-2xs">
           <div className="flex items-center gap-2 min-w-0">
            <span className={`w-2 h-2 rounded-full shrink-0 ${cls}`} />
            <span className="text-foreground truncate">{s.name}</span>
           </div>
           <span className={`tabular-nums shrink-0 ${ok ? "text-muted-foreground" : warn ? "text-warning font-semibold" : "text-destructive font-semibold"}`}>
            {s.latency_ms != null ? `${s.latency_ms}ms` : s.status}
           </span>
          </div>
         );
        })
       )}
      </CardContent>
     </Card>
    </div>
   )}

   {/* Content row: sources + escalamientos pendientes */}
   <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
    {/* Recent sources */}
    <Card>
     <CardHeader className="flex-row items-center justify-between pb-4 border-b">
      <div>
        <CardTitle className="text-15 font-semibold">Base de conocimiento</CardTitle>
        <p className="text-2xs text-muted-foreground mt-0.5">{sources.length} documentos</p>
      </div>
      <Link href="/dashboard/conocimiento/documentos">
       <Button variant="ghost" size="sm" className="gap-1 text-muted-foreground h-7 text-xs">
        Ver todos <ArrowUpRight className="h-3 w-3" />
       </Button>
      </Link>
     </CardHeader>
     {loadingContent ? (
      <CardContent className="space-y-2 pt-4">
       {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
      </CardContent>
     ) : recentSources.length === 0 ? (
      <CardContent>
       <EmptyState
        icon={Database}
        title="Sin documentos"
        description="La base de conocimiento está vacía. Suba su primer PDF o conecte una URL para que el bot pueda responder."
        action={can(PERM.KNOWLEDGE_UPDATE) ? (
         <Link href="/dashboard/conocimiento/documentos">
          <Button size="sm" className="gap-1.5">
           <Upload className="w-3.5 h-3.5" /> Subir primer documento
          </Button>
         </Link>
        ) : undefined}
       />
      </CardContent>
     ) : (
      <div className="divide-y">
       {recentSources.map((s) => (
        <Link
         key={s.id}
         href={`/dashboard/conocimiento/documentos/${s.id}/chunks`}
         className="group flex items-center gap-3 px-5 py-3 hover:bg-muted/30 transition-colors"
        >
         <div className={`h-2 w-2 shrink-0 rounded-full ${
          s.status === "ready" ? "bg-success" :
          s.status === "error" ? "bg-destructive" : "bg-warning animate-pulse"
         }`} />
         <div className="min-w-0 flex-1">
           <p className="truncate text-13 font-medium">{s.name}</p>
           <p className="mt-0.5 text-2xs text-muted-foreground tabular-nums">
           {s.type.toUpperCase()} · {s.chunk_count ?? 0} chunks
          </p>
         </div>
         <Badge
          variant={s.status === "ready" ? "success" : s.status === "error" ? "destructive" : "warning"}
          className="text-3xs shrink-0"
         >
          {s.status === "ready" ? "Listo" : s.status === "error" ? "Error" : "Procesando"}
         </Badge>
        </Link>
       ))}
      </div>
     )}
    </Card>

    {/* Escalamientos pendientes */}
    <Card>
     <CardHeader className="flex-row items-center justify-between pb-4 border-b">
      <div>
        <CardTitle className="text-15 font-semibold">Escalamientos pendientes</CardTitle>
        <p className="text-2xs text-muted-foreground mt-0.5">Conversaciones que esperan atención humana</p>
      </div>
      <Link href="/dashboard/conversaciones/escalamientos">
       <Button variant="ghost" size="sm" className="gap-1 text-muted-foreground h-7 text-xs">
        Ver bandeja <ArrowUpRight className="h-3 w-3" />
       </Button>
      </Link>
     </CardHeader>
     {loadingContent ? (
      <CardContent className="space-y-2 pt-4">
       {[1, 2, 3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
      </CardContent>
     ) : escalations.length === 0 ? (
      <CardContent>
       <EmptyState
        icon={CheckCircle2}
        title="Sin escalamientos"
        description="Todas las conversaciones están resueltas"
       />
      </CardContent>
     ) : (
      <div className="divide-y">
       {escalations.map((c) => {
        const refTime = new Date(c.last_message_at ?? c.started_at).getTime();
        const msAgo = Number.isFinite(refTime) ? Date.now() - refTime : 0;
        const hAgo = Math.floor(msAgo / 3_600_000);
        const minAgo = Math.floor(msAgo / 60_000);
        const timeLabel = hAgo > 0 ? `${hAgo}h` : `${minAgo}m`;
        const urgent = hAgo >= 4;
        return (
         <Link
          key={c.id}
          href="/dashboard/conversaciones/escalamientos"
          className="flex items-center gap-3 px-5 py-3 hover:bg-muted/30 transition-colors"
         >
          <UserRound className={`h-4 w-4 shrink-0 ${urgent ? "text-destructive" : "text-warning"}`} />
          <div className="min-w-0 flex-1">
            <p className="truncate text-13 font-medium">{c.first_user_message ?? "(sin mensaje)"}</p>
            <p className="mt-0.5 text-2xs text-muted-foreground tabular-nums">
            {c.message_count} mensajes · esperando {timeLabel}
           </p>
          </div>
          {urgent && <Badge variant="destructive" className="text-3xs shrink-0">Urgente</Badge>}
         </Link>
        );
       })}
      </div>
     )}
    </Card>
   </div>

   {/* Provider status */}
   {can(PERM.SYSTEM_MANAGE) ? (
    <Card>
     <CardHeader className="flex-row items-center justify-between pb-4 border-b">
      <div>
        <CardTitle className="text-15 font-semibold">Proveedores LLM</CardTitle>
        <p className="text-2xs text-muted-foreground mt-0.5">{activeProviders.length} activos en cadena</p>
      </div>
       <Link href="/dashboard/configuracion/proveedores">
       <Button variant="ghost" size="sm" className="text-2xs text-muted-foreground h-7">Gestionar</Button>
      </Link>
     </CardHeader>
     <CardContent className="pt-4">
      {loadingAdmin ? (
       <div className="space-y-3">
        {[1, 2, 3].map((i) => <Skeleton key={i} className="h-9 w-full" />)}
       </div>
      ) : activeProviders.length === 0 ? (
       <EmptyState
        icon={Cpu}
        title="Sin proveedores activos"
        description="El bot necesita un modelo de IA para responder. Conecta Groq, OpenAI, Gemini u otro."
        action={can(PERM.SYSTEM_MANAGE) ? (
         <Link href="/dashboard/configuracion">
          <Button size="sm" className="gap-1.5">
           <Cpu className="w-3.5 h-3.5" /> Configurar IA
          </Button>
         </Link>
        ) : undefined}
       />
      ) : (
       <div className="space-y-2">
        {activeProviders.slice(0, 4).map((p) => (
         <div key={p.id} className="flex items-center gap-3 rounded-lg border px-3 py-2.5 bg-muted/30">
          <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-success/10 text-success">
           <CheckCircle2 className="h-3 w-3" />
          </span>
          <div className="flex-1 min-w-0">
           <p className="text-13 font-medium truncate">{p.name}</p>
           <p className="text-2xs text-muted-foreground">{p.model_name}</p>
          </div>
          <Badge variant="secondary" className="text-3xs font-mono shrink-0">#{p.priority}</Badge>
         </div>
        ))}
       </div>
      )}
     </CardContent>
    </Card>
   ) : null}
  </div>
 );
}


function QuickAction({
 href, icon: Icon, label, hint,
}: {
 href: string;
 icon: typeof Upload;
 label: string;
 hint: string;
}) {
 return (
  <Link
   href={href}
   className="group flex items-center gap-3 rounded-xl border border-border bg-card px-4 py-3 hover:bg-muted/30 hover:border-primary/40 transition-colors"
  >
   <div className="p-2 rounded-lg bg-primary/10 text-primary shrink-0">
    <Icon className="h-4 w-4" />
   </div>
   <div className="min-w-0 flex-1">
    <p className="text-13 font-medium truncate">{label}</p>
    <p className="text-2xs text-muted-foreground truncate">{hint}</p>
   </div>
   <ArrowUpRight className="h-4 w-4 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0" />
  </Link>
 );
}

function SecurityRow({
 icon: Icon, label, value, bad,
}: {
 icon: typeof ShieldAlert;
 label: string;
 value: number;
 bad: boolean;
}) {
 return (
  <div className="flex items-center justify-between gap-2">
   <div className="flex items-center gap-2 min-w-0">
    <Icon className={`h-3.5 w-3.5 shrink-0 ${bad ? "text-destructive" : "text-muted-foreground"}`} />
    <span className="text-13 text-foreground truncate">{label}</span>
   </div>
   <span className={`text-13 font-semibold tabular-nums shrink-0 ${bad ? "text-destructive" : "text-muted-foreground"}`}>
    {value}
   </span>
  </div>
 );
}

type CyclePhase = "docs" | "test" | "deploy";
type PhaseState = "ok" | "pending" | "unavailable";

function WorkflowCycle({
 providers,
 deployStatus,
 loading,
}: {
 providers: LLMProvider[];
 deployStatus: {
  last_deployed_at: string | null;
  pending_sources: number;
  config_changed_since_deploy: boolean;
  never_deployed: boolean;
 } | null;
 loading: boolean;
}) {
 const hasActiveProvider = providers.some((p) => p.is_active && p.priority !== null);

 const phaseState: Record<CyclePhase, PhaseState> = {
  docs:   deployStatus
   ? (deployStatus.pending_sources > 0 ? "pending" : "ok")
   : "unavailable",
  test:   hasActiveProvider ? "ok" : "pending",
  deploy: deployStatus
   ? (deployStatus.config_changed_since_deploy || deployStatus.pending_sources > 0 ? "pending" : "ok")
   : "unavailable",
 };

 const allOk = !loading && deployStatus && Object.values(phaseState).every((s) => s === "ok");
 const hasPending = Object.values(phaseState).some((s) => s === "pending");

 const phases: { key: CyclePhase; label: string; hintOk: string; hintPending: string; href: string }[] = [
  {
   key: "docs",
   label: "Documentos",
   hintOk: "Base de conocimiento al día",
   hintPending: `${deployStatus?.pending_sources ?? 0} doc${(deployStatus?.pending_sources ?? 0) !== 1 ? "s" : ""} sin publicar`,
   href: "/dashboard/conocimiento/documentos",
  },
  {
   key: "test",
   label: "Pruebas",
   hintOk: "Servicio de IA activo",
   hintPending: "Sin servicio de IA activo",
    href: "/dashboard/configuracion/playground",
  },
  {
   key: "deploy",
   label: "Publicación",
   hintOk: deployStatus?.last_deployed_at
    ? `Publicado ${new Date(deployStatus.last_deployed_at).toLocaleDateString("es", { day: "numeric", month: "short" })}`
    : "Sin despliegues",
   hintPending: "Hay cambios sin publicar",
   href: "/dashboard/configuracion/publicaciones",
  },
 ];

 return (
  <div className={`mb-6 rounded-xl border bg-card p-4 transition-colors ${
   allOk ? "border-success/30" : hasPending ? "border-warning/30" : "border-border"
  }`}>
   <div className="flex items-center justify-between mb-3">
    <div>
      <p className="text-15 font-semibold">Ciclo de publicación</p>
     <p className="text-2xs text-muted-foreground mt-0.5">
      {loading
       ? "Verificando estado..."
       : allOk
        ? "Todo publicado y al día"
        : "Hay pasos pendientes antes de publicar"}
     </p>
    </div>
    {allOk && !loading && (
     <span className="flex items-center gap-1 text-xs font-semibold text-success">
      <CheckCircle2 className="h-3.5 w-3.5" /> Al día
     </span>
    )}
   </div>

   <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
    {phases.map((phase, i) => {
     const state = loading ? "unavailable" : phaseState[phase.key];
     const isOk      = state === "ok";
     const isPending = state === "pending";

     return (
      <Link
       key={phase.key}
       href={phase.href}
       className={`group flex flex-col gap-1 rounded-lg border px-3 py-2.5 transition-colors ${
        isOk
         ? "border-success/30 bg-success/5 hover:bg-success/10"
         : isPending
          ? "border-warning/40 bg-warning/5 hover:bg-warning/10"
          : "border-border bg-muted/30 hover:bg-muted/50"
       }`}
      >
       <div className="flex items-center justify-between gap-1">
        <div className="flex items-center gap-1.5 min-w-0">
         <span className={`flex h-4 w-4 shrink-0 items-center justify-center rounded-full text-3xs font-bold ${
          isOk      ? "bg-success text-white"
          : isPending ? "bg-warning text-white"
          : "bg-muted-foreground/20 text-muted-foreground"
         }`}>
          {isOk ? "✓" : i + 1}
         </span>
         <span className={`text-xs font-semibold truncate ${
          isOk ? "text-success" : isPending ? "text-warning" : "text-muted-foreground"
         }`}>
          {phase.label}
         </span>
        </div>
        <ChevronRight className={`h-3 w-3 shrink-0 transition-transform group-hover:translate-x-0.5 ${
         isOk ? "text-success/50" : isPending ? "text-warning" : "text-muted-foreground/40"
        }`} />
       </div>
       <p className="text-3xs text-muted-foreground leading-tight pl-5.5">
        {loading ? "—" : isOk ? phase.hintOk : phase.hintPending}
       </p>
      </Link>
     );
    })}
   </div>
  </div>
 );
}
