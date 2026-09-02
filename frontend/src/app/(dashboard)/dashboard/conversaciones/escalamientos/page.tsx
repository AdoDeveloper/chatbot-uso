"use client";

import { useEffect, useMemo, useState } from "react";
import {
  Loader2, CheckCircle2, MessageSquare, TrendingUp, Timer, Star,
  ExternalLink, Tag, X as XIcon,
} from "lucide-react";
import Link from "next/link";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import type { ChatConversationOut, ConversationStatus, ConversationTag, EscalationTrigger } from "@/types";
import { Input } from "@/components/ui/input";
import { Select, SelectOption } from "@/components/ui/select";
import { EmptyState } from "@/components/ui/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ConversacionesTabs } from "../_components/ConversacionesTabs";
import { SegmentedControl } from "@/components/composed/segmented-control";
import { TablePagination } from "@/components/composed/table-pagination";
import { StatCard } from "@/components/composed/stat-card";
import { PageHeader } from "@/components/ui/page-header";
import { formatInProjectTz } from "@/lib/datetime";
import { TRIGGER_LABEL_SHORT } from "@/lib/escalation-labels";

interface EscalationMetrics {
  days: number;
  total: number;
  by_status: Record<string, number>;
  by_trigger: Record<string, number>;
  avg_resolution_seconds: number | null;
  resolved_count: number;
  resolution_rate: number | null;
  csat_avg: number | null;
}

function formatDuration(seconds: number | null) {
  if (seconds == null) return "-";
  const h = Math.floor(seconds / 3600);
  const m = Math.round((seconds % 3600) / 60);
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}

function MetricsPanel({ metrics, loading }: { metrics: EscalationMetrics | null; loading: boolean }) {
  const triggerEntries = Object.entries(metrics?.by_trigger ?? {}).sort((a, b) => b[1] - a[1]);
  const triggerTotal = triggerEntries.reduce((sum, [, n]) => sum + n, 0);

  return (
    <div className="mb-4 space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <StatCard
          title="Escalamientos"
          value={metrics ? String(metrics.total) : "-"}
          description="Últimos 30 días"
          icon={MessageSquare}
          loading={loading}
        />
        <StatCard
          title="Tasa de resolución"
          value={metrics?.resolution_rate != null ? `${Math.round(metrics.resolution_rate * 100)}%` : "-"}
          description={metrics ? `${metrics.resolved_count} resueltos` : undefined}
          icon={TrendingUp}
          accent="green"
          loading={loading}
        />
        <StatCard
          title="Tiempo de resolución"
          value={formatDuration(metrics?.avg_resolution_seconds ?? null)}
          description="Promedio"
          icon={Timer}
          accent="teal"
          loading={loading}
        />
        <StatCard
          title="CSAT promedio"
          value={metrics?.csat_avg != null ? `${metrics.csat_avg.toFixed(1)}/5` : "-"}
          description="De quienes valoraron"
          icon={Star}
          accent="amber"
          loading={loading}
        />
      </div>

      {!loading && triggerEntries.length > 0 && (
        <Card className="p-4">
          <p className="text-2xs font-semibold uppercase tracking-wider text-muted-foreground mb-3">
            Motivos de escalamiento
          </p>
          <div className="space-y-2">
            {triggerEntries.map(([trigger, count]) => {
              const pct = triggerTotal > 0 ? Math.round((count / triggerTotal) * 100) : 0;
              const label = TRIGGER_LABEL_SHORT[trigger as EscalationTrigger | "manual"] ?? trigger;
              return (
                <div key={trigger} className="flex items-center gap-3">
                  <span className="text-13 text-foreground w-40 shrink-0 truncate">{label}</span>
                  <div className="flex-1 h-1.5 rounded-full bg-muted overflow-hidden">
                    <div className="h-full rounded-full bg-primary" style={{ width: `${pct}%` }} />
                  </div>
                  <span className="text-2xs text-muted-foreground tabular-nums w-14 text-right shrink-0">
                    {count} ({pct}%)
                  </span>
                </div>
              );
            })}
          </div>
        </Card>
      )}
    </div>
  );
}

function deviceLabel(browser: string | null) {
  return browser || "Desconocido";
}

type BadgeVariant = "secondary" | "warning" | "info" | "success" | "muted";
const STATUS_BADGE: Record<ConversationStatus, { label: string; variant: BadgeVariant }> = {
  active:       { label: "Activa",      variant: "secondary" },
  escalated:    { label: "Pendiente",   variant: "warning"   },
  resolved:     { label: "Resuelto",    variant: "success"   },
};

type FilterState = "escalated" | "resolved";

const FILTER_LABELS: Record<FilterState, string> = {
  escalated:    "Pendientes",
  resolved:     "Resueltos",
};

const TRIGGER_DISPLAY = TRIGGER_LABEL_SHORT;

function CaseCard({
  conv,
  selected,
  onToggleSelect,
  onResolve,
  resolving,
  csatReasonLabels,
}: {
  conv: ChatConversationOut;
  selected: boolean;
  onToggleSelect: (id: string) => void;
  onResolve: (id: string) => void;
  resolving: boolean;
  csatReasonLabels: Record<string, string>;
}) {
  const badge = STATUS_BADGE[conv.status];

  return (
    <Card className={selected ? "border-primary/50 bg-primary/5" : undefined}>
      <div className="px-5 py-3 flex items-start gap-3 flex-wrap sm:flex-nowrap">
        <input
          type="checkbox"
          checked={selected}
          onChange={() => onToggleSelect(conv.id)}
          className="mt-1 h-3.5 w-3.5 accent-primary shrink-0 cursor-pointer"
        />

        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1 flex-wrap">
            <Badge variant={badge.variant} size="xs">{badge.label}</Badge>
            <span className="text-2xs text-muted-foreground font-mono">#{conv.id.slice(0, 8)}</span>
            <span className="text-2xs text-muted-foreground">{deviceLabel(conv.browser)}</span>
            {conv.csat_score != null && (
              <Badge variant="success" size="xs">CSAT {conv.csat_score}/5</Badge>
            )}
            {conv.escalation_trigger_reason && (
              <Badge variant="warning" size="xs" className="max-w-40 sm:max-w-56 truncate" title={conv.escalation_trigger_reason}>
                {TRIGGER_DISPLAY[conv.escalation_trigger_reason.split(":")[0]?.trim() as keyof typeof TRIGGER_DISPLAY] ?? conv.escalation_trigger_reason}
              </Badge>
            )}
            {(conv.tags ?? []).slice(0, 4).map((t) => (
              <Badge key={t} variant="outline" size="xs">#{t}</Badge>
            ))}
            {(conv.tags ?? []).length > 4 && (
              <span className="text-3xs text-muted-foreground">+{conv.tags.length - 4}</span>
            )}
          </div>

          <p className="text-13 text-foreground leading-snug line-clamp-2">
            {conv.first_user_message ?? "(sin mensaje)"}
          </p>

          {(conv.csat_reasons?.length > 0 || conv.csat_comment) && (
            <div className="mt-1.5 flex flex-col gap-1">
              {conv.csat_reasons?.length > 0 && (
                <div className="flex items-center gap-1 flex-wrap">
                  {conv.csat_reasons.map((r) => (
                    <Badge key={r} variant="muted" size="xs">
                      {csatReasonLabels[r] ?? r}
                    </Badge>
                  ))}
                </div>
              )}
              {conv.csat_comment && (
                <p className="text-2xs text-muted-foreground italic leading-snug line-clamp-2">
                  &quot;{conv.csat_comment}&quot;
                </p>
              )}
            </div>
          )}

          <div className="flex items-center gap-3 mt-2 text-2xs text-muted-foreground flex-wrap">
            <span className="flex items-center gap-1">
              <MessageSquare className="w-3 h-3" />
              {conv.message_count} mensajes
            </span>
            <span>
              Inicio: {formatInProjectTz(conv.started_at, {
                day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
              })}
            </span>
            {conv.resolved_at && (
              <span className="text-success">
                Resuelto: {formatInProjectTz(conv.resolved_at, {
                  day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit",
                })}
              </span>
            )}
          </div>
        </div>

        <div className="flex items-center gap-2 w-full sm:w-auto flex-wrap sm:flex-nowrap">
          {conv.status === "escalated" && (
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5 text-xs shrink-0 w-full sm:w-auto"
              disabled={resolving}
              onClick={() => onResolve(conv.id)}
            >
              {resolving ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
              Marcar resuelto
            </Button>
          )}
          <Link href={`/dashboard/conversaciones?id=${conv.id}`} className="w-full sm:w-auto">
            <Button variant="outline" size="sm" className="gap-1.5 text-xs shrink-0 w-full sm:w-auto">
              <ExternalLink className="w-3 h-3" />
              Ver
            </Button>
          </Link>
        </div>
      </div>
    </Card>
  );
}

interface ConversationPage {
  items: ChatConversationOut[];
  total: number;
}

export default function EscalamientosPage() {
  const { toast, confirm } = useToast();
  const [filter, setFilter] = useState<FilterState>("escalated");
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);

  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkTagInput, setBulkTagInput] = useState("");
  const [tagFilter, setTagFilter] = useState<string>("");
  const [resolvingIds, setResolvingIds] = useState<Set<string>>(new Set());

  const { data: knownTagsData, refetch: refetchTags } = useApi<ConversationTag[]>("/conversations/tags");
  const knownTags = knownTagsData ?? [];

  const { data: metrics, loading: metricsLoading, error: metricsError, refetch: refetchMetrics } = useApi<EscalationMetrics>("/escalation/metrics?days=30");

  const { data: csatReasonLabelsData } = useApi<Record<string, string>>("/conversations/csat-reason-labels");
  const csatReasonLabels = csatReasonLabelsData ?? {};

  const baseQuery = useMemo(() => {
    const tagParam = tagFilter ? `&tag=${encodeURIComponent(tagFilter)}` : "";
    return `page=${page}&page_size=${pageSize}&source=production${tagParam}`;
  }, [page, pageSize, tagFilter]);

  const primaryQ = useApi<ConversationPage>(
    `/conversations?status=${filter}&${baseQuery}`,
  );

  const loading = primaryQ.loading;

  const cases = useMemo<ChatConversationOut[]>(
    () => primaryQ.data?.items ?? [],
    [primaryQ.data],
  );

  const total = primaryQ.data?.total ?? 0;

  const loadError = primaryQ.error;
  useEffect(() => {
    if (loadError) toast({ type: "error", message: "Error al cargar los escalamientos." });
  }, [loadError, toast]);

  // Limpia la selección al cambiar de filtro: evita bulk actions sobre IDs ya no visibles.
  useEffect(() => {
    setSelectedIds(new Set());
  }, [filter, tagFilter]);

  async function load() {
    await Promise.all([primaryQ.refetch(), refetchMetrics()]);
    toast({ type: "success", message: "Escalamientos actualizados.", duration: 2000 });
  }

  function toggleSelect(id: string) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      next.has(id) ? next.delete(id) : next.add(id);
      return next;
    });
  }

  function clearSelection() { setSelectedIds(new Set()); }

  async function bulkApply(action: "add_tag" | "remove_tag") {
    if (selectedIds.size === 0 || !bulkTagInput.trim()) {
      toast({ type: "error", message: "Seleccione conversaciones e ingrese un tag." });
      return;
    }
    setBulkBusy(true);
    try {
      const { data } = await api.post<{ affected: number; errors: { id: string; error: string }[] }>("/conversations/bulk", {
        conversation_ids: Array.from(selectedIds),
        action,
        tag: bulkTagInput.trim(),
      });
      const errs = data.errors?.length ?? 0;
      toast({
        type: errs > 0 ? "warning" : "success",
        message: `${data.affected} conversaciones afectadas${errs ? ` · ${errs} con error` : ""}.`,
      });
      clearSelection();
      setBulkTagInput("");
      await load();
      void refetchTags();
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al aplicar la acción.") });
    } finally {
      setBulkBusy(false);
    }
  }

  async function resolveOne(id: string) {
    const ok = await confirm({
      title: "¿Marcar como resuelta?",
      message: "La conversación pasará a la pestaña de resueltos.",
      confirmText: "Marcar resuelta",
    });
    if (!ok) return;
    setResolvingIds((prev) => new Set(prev).add(id));
    try {
      const { data } = await api.post<{ affected: number; errors: { id: string; error: string }[] }>("/conversations/bulk", {
        conversation_ids: [id],
        action: "resolve",
      });
      if (data.affected > 0) {
        toast({ message: "Conversación marcada como resuelta.", type: "success" });
        await load();
      } else {
        toast({ message: "No se pudo marcar como resuelta.", type: "error" });
      }
    } catch (err) {
      toast({ message: getErrorMessage(err, "Error al marcar como resuelta."), type: "error" });
    } finally {
      setResolvingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
    }
  }

  async function bulkResolve() {
    if (selectedIds.size === 0) return;
    const ok = await confirm({
      title: "¿Marcar como resueltas?",
      message: `${selectedIds.size} conversación${selectedIds.size !== 1 ? "es" : ""} seleccionada${selectedIds.size !== 1 ? "s" : ""} pasará${selectedIds.size !== 1 ? "n" : ""} a la pestaña de resueltos.`,
      confirmText: "Marcar resueltas",
    });
    if (!ok) return;
    setBulkBusy(true);
    try {
      const { data } = await api.post<{ affected: number; errors: { id: string; error: string }[] }>("/conversations/bulk", {
        conversation_ids: Array.from(selectedIds),
        action: "resolve",
      });
      const errs = data.errors?.length ?? 0;
      toast({
        type: errs > 0 ? "warning" : "success",
        message: `${data.affected} conversaciones marcadas como resueltas${errs ? ` · ${errs} con error` : ""}.`,
      });
      clearSelection();
      await load();
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al marcar como resueltas.") });
    } finally {
      setBulkBusy(false);
    }
  }

  return (
    <div>
      <PageHeader
        icon={MessageSquare}
        title="Conversaciones"
        tip="Historial del chatbot, preguntas sin responder y chats escalados."
      />

      <ConversacionesTabs />

      {!metricsError && <MetricsPanel metrics={metrics} loading={metricsLoading} />}

      <Card className="overflow-hidden">
        {/* Encabezado: contador + filtros */}
        <div className="flex flex-col gap-3 px-5 py-4 border-b border-border/60">
          <div className="flex items-center gap-2">
            <h2 className="text-base font-semibold flex-1 min-w-0 truncate">{FILTER_LABELS[filter]}</h2>
            {!loading && (
              <Badge variant="outline" className="tabular-nums shrink-0">
                {total} caso{total !== 1 ? "s" : ""}
              </Badge>
            )}
          </div>
          <div className="flex items-center flex-wrap">
            <SegmentedControl
              ariaLabel="Filtrar por estado"
              variant="chip"
              value={filter}
              onChange={(v) => { setFilter(v); setPage(1); }}
              options={(Object.keys(FILTER_LABELS) as FilterState[]).map((key) => ({ value: key, label: FILTER_LABELS[key] }))}
            />
          </div>

          {knownTags.length > 0 && (
            <div className="grid grid-cols-1 gap-2 sm:flex sm:justify-end">
              <Select
                value={tagFilter}
                onChange={(e) => { setTagFilter(e.target.value); setPage(1); }}
                className="h-8 text-13 min-w-0"
              >
                <SelectOption value="">Todos los tags</SelectOption>
                {knownTags.slice(0, 30).map((t) => (
                  <SelectOption key={t.tag} value={t.tag}>#{t.tag} ({t.count})</SelectOption>
                ))}
              </Select>
            </div>
          )}
        </div>

        {/* Lista */}
        {loading ? (
          <div className="p-5 space-y-3">
            {[1, 2, 3].map((i) => <Skeleton key={i} className="h-24 w-full rounded-xl" />)}
          </div>
        ) : cases.length === 0 ? (
          <EmptyState
            icon={CheckCircle2}
            title={`Sin casos en "${FILTER_LABELS[filter]}"`}
            description="Cambia el filtro para ver otros casos"
          />
        ) : (
          <div className="p-5 space-y-2">
            {cases.map((conv) => (
              <CaseCard
                key={conv.id}
                conv={conv}
                selected={selectedIds.has(conv.id)}
                onToggleSelect={toggleSelect}
                onResolve={resolveOne}
                csatReasonLabels={csatReasonLabels}
                resolving={resolvingIds.has(conv.id)}
              />
            ))}
          </div>
        )}

        {cases.length > 0 && (
          <TablePagination
            total={total}
            page={page}
            pageSize={pageSize}
            onPageChange={setPage}
            onPageSizeChange={(n) => { setPageSize(n); setPage(1); }}
            itemLabel="casos"
          />
        )}
      </Card>

      {/* Barra de bulk tags */}
      {selectedIds.size > 0 && (
        <div className="fixed bottom-4 left-1/2 -translate-x-1/2 z-40 bg-card border border-primary/40 shadow-xl rounded-xl px-4 py-3 flex items-center gap-3 flex-wrap max-w-[95vw]">
<span className="text-13 font-medium tabular-nums">
            {selectedIds.size} seleccionada{selectedIds.size !== 1 ? "s" : ""}
           </span>
          <Button size="sm" variant="ghost" onClick={clearSelection} className="h-7 px-2 text-xs">
            <XIcon className="w-3 h-3 mr-1" /> Limpiar
          </Button>
          <div className="h-6 w-px bg-border" />
          <Button
            size="sm"
            variant="outline"
            onClick={bulkResolve}
            disabled={bulkBusy}
            className="gap-1.5 text-xs h-7"
          >
            {bulkBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : <CheckCircle2 className="w-3 h-3" />}
            Marcar resueltas
          </Button>
          <div className="h-6 w-px bg-border" />
          <Input
            value={bulkTagInput}
            onChange={(e) => setBulkTagInput(e.target.value)}
            placeholder="tag..."
            className="h-7 text-xs w-28"
          />
          <Button
            size="sm"
            variant="outline"
            onClick={() => bulkApply("add_tag")}
            disabled={bulkBusy || !bulkTagInput.trim()}
            className="gap-1.5 text-xs h-7"
          >
            <Tag className="w-3 h-3" /> +Tag
          </Button>
          <Button
            size="sm"
            variant="ghost"
            onClick={() => bulkApply("remove_tag")}
            disabled={bulkBusy || !bulkTagInput.trim()}
            className="gap-1.5 text-xs h-7 text-muted-foreground"
          >
            {bulkBusy ? <Loader2 className="w-3 h-3 animate-spin" /> : null} −Tag
          </Button>
        </div>
      )}
    </div>
  );
}
