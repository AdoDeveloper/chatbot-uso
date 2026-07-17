"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import dynamic from "next/dynamic";
import {
  Plus, Database, Search, X, XCircle, Loader2,
} from "lucide-react";
import api from "@/lib/api";
import type { Source } from "@/types";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { usePermission } from "@/hooks/use-permission";
import { PERM } from "@/lib/permissions";
import { useToast } from "@/components/ui/toast";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Skeleton } from "@/components/ui/skeleton";
import { PageHeader } from "@/components/ui/page-header";
import { StatCard } from "@/components/composed/stat-card";
import { Modal } from "@/components/composed/modal";
import { Card } from "@/components/ui/card";
import { DataTable } from "@/components/composed/data-table";
import { EmptyState } from "@/components/ui/empty-state";

import { SourceRow } from "./_components/SourceRow";
import { AddSourcePanel } from "./_components/AddSourcePanel";
import { mergeSources } from "./_components/sources-helpers";

function SourcesListContent() {
  const { confirm, toast } = useToast();
  const can = usePermission();
  const { data, loading, error, refetch: load, setData } = useApi<Source[]>("/sources");
  const sources = data ?? [];
  const setSources = useCallback(
    (fn: (prev: Source[]) => Source[]) => setData((prev) => fn(prev ?? [])),
    [setData]
  );
  const [search, setSearch] = useState("");
  const [activeTagFilter, setActiveTagFilter] = useState<string | null>(null);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(20);
  const [panelOpen, setPanelOpen] = useState(false);
  const [reviewing, setReviewing] = useState<string | null>(null);
  const [rejectModal, setRejectModal] = useState<{ source: Source; reason: string; saving: boolean } | null>(null);
  const sourcesRef = useRef(sources);
  sourcesRef.current = sources;

  useEffect(() => {
    if (error) toast({ type: "error", message: "No se pudo cargar la base de conocimiento." });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [error]);

  const hasBusy = sources.some((s) => s.status === "processing" || s.status === "pending");
  useEffect(() => {
    if (!hasBusy) return;
    const interval = setInterval(() => {
      api.get<Source[]>("/sources")
        .then(({ data }) => setSources((prev) => mergeSources(prev, data)))
        .catch(() => {});
    }, 2000);
    return () => clearInterval(interval);
  }, [hasBusy, setSources]);

  const handleReingest = async (s: Source) => {
    setSources((prev) => prev.map((x) => x.id === s.id ? { ...x, status: "pending" as const, error_message: null, progress_stage: null } : x));
    try { await api.post(`/sources/${s.id}/ingest`); }
    catch { load(); }
  };

  const handleDelete = async (s: Source) => {
    const ok = await confirm({
      title: `¿Eliminar "${s.name}"?`,
      message: "Se eliminarán todos los vectores del índice",
      confirmText: "Eliminar", variant: "danger",
    });
    if (!ok) return;
    try {
      await api.delete(`/sources/${s.id}`);
      setSources((prev) => prev.filter((x) => x.id !== s.id));
    } catch (err: unknown) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo eliminar la fuente.") });
    }
  };

  const handleApprove = async (s: Source) => {
    const ok = await confirm({
      title: `¿Aprobar "${s.name}"?`,
      message: "Al aprobar confirmas que la fuente es correcta. El chatbot podrá consultarla.",
      confirmText: "Aprobar",
    });
    if (!ok) return;

    setReviewing(s.id);
    try {
      const { data } = await api.post(`/sources/${s.id}/approve`);
      setSources((prev) => prev.map((x) => x.id === s.id
        ? { ...x, review_status: "aprobada" as const, reviewed_at: data.reviewed_at, reviewed_by_name: data.reviewed_by_name }
        : x));
      toast({ type: "success", message: `"${s.name}" aprobada.` });
    } catch (err: unknown) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo aprobar la fuente.") });
    } finally {
      setReviewing(null);
    }
  };

  const handleReject = (s: Source) => {
    setRejectModal({ source: s, reason: "", saving: false });
  };

  const submitReject = async () => {
    if (!rejectModal || !rejectModal.reason.trim()) return;
    const { source, reason } = rejectModal;
    setRejectModal((m) => m ? { ...m, saving: true } : null);
    setReviewing(source.id);
    try {
      await api.post(`/sources/${source.id}/reject`, { reason: reason.trim() });
      setSources((prev) => prev.map((x) => x.id === source.id
        ? { ...x, review_status: "rechazada" as const, rejection_reason: reason.trim() }
        : x));
      toast({ type: "success", message: `"${source.name}" rechazada.` });
      setRejectModal(null);
    } catch (err: unknown) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo rechazar la fuente.") });
      setRejectModal((m) => m ? { ...m, saving: false } : null);
    } finally {
      setReviewing(null);
    }
  };

  const allTags = Array.from(new Set(sources.flatMap((s) => s.tags ?? [])));

  const filtered = sources.filter((s) => {
    if (search && !s.name.toLowerCase().includes(search.toLowerCase())) return false;
    if (activeTagFilter && !(s.tags ?? []).includes(activeTagFilter)) return false;
    return true;
  });

  useEffect(() => { setPage(1); }, [search, activeTagFilter]);
  const paginated = filtered.slice((page - 1) * pageSize, page * pageSize);

  const ready = sources.filter((s) => s.status === "ready").length;
  const errors = sources.filter((s) => s.status === "error").length;
  const totalChunks = sources.reduce((n, s) => n + s.chunk_count, 0);

  return (
    <div className="max-w-6xl mx-auto space-y-6">
      <AddSourcePanel open={panelOpen} onClose={() => setPanelOpen(false)} onCreated={load} />

      {/* Stats como cards (Stripe / Linear pattern):
          padding p-5, label uppercase 11px, valor 24px tabular-nums, hint debajo.
          Grid responsive: 1 col móvil, 2 col tablet, 4 col desktop. */}
      <div className={`grid grid-cols-1 sm:grid-cols-2 ${errors > 0 ? "lg:grid-cols-4" : "lg:grid-cols-3"} gap-3`}>
        <StatCard
          title="Totales"
          value={sources.length}
          tip="Cantidad de fuentes (activas + con error + en proceso)."
        />
        <StatCard
          title="Listas"
          value={ready}
          accent="green"
          tip="Fuentes con ingesta terminada. Solo las aprobadas son visibles al chatbot."
        />
        <StatCard
          title="Chunks indexados"
          value={totalChunks.toLocaleString()}
          tip="Fragmentos almacenados en el índice vectorial."
        />
        {errors > 0 && (
          <StatCard
            title="Con error"
            value={errors}
            accent="red"
            tip="Fuentes que fallaron en ingesta. Click en 'Reingestar' tras corregir el problema."
          />
        )}
      </div>

      <Card className="overflow-hidden">
        {/* Fila 1: búsqueda + acción primaria, siempre juntas y visibles.
            Los filtros de tags (que pueden crecer mucho) van en su propia
            fila para no empujar el botón "Agregar" fuera de vista. */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-border/60">
          <div className="relative flex-1 min-w-0 max-w-64">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <Input
              value={search} onChange={(e) => setSearch(e.target.value)}
              placeholder="Buscar fuentes..."
              className="pl-8 h-8 w-full"
            />
          </div>

          {can(PERM.KNOWLEDGE_UPDATE) && (
            <Button size="sm" onClick={() => setPanelOpen(true)} className="gap-1.5 ml-auto shrink-0">
              <Plus className="w-3.5 h-3.5" /> Agregar
            </Button>
          )}
        </div>

        {allTags.length > 0 && (
          <div className="flex items-center gap-1.5 flex-wrap px-5 py-2.5 border-b border-border/60 bg-muted/20">
            <span className="text-2xs text-muted-foreground font-medium uppercase tracking-wider">Tags:</span>
            {activeTagFilter && (
              <button
                onClick={() => setActiveTagFilter(null)}
                className="flex items-center gap-1 px-2 py-0.5 bg-muted text-muted-foreground text-2xs rounded-full hover:bg-muted/80 transition"
              >
                <X className="w-3 h-3" /> Limpiar
              </button>
            )}
            {allTags.map((tag) => (
              <button
                key={tag}
                onClick={() => setActiveTagFilter(activeTagFilter === tag ? null : tag)}
                className={`px-2 py-0.5 text-2xs rounded-full border transition ${
                  activeTagFilter === tag
                    ? "bg-primary text-primary-foreground border-primary"
                    : "bg-secondary text-secondary-foreground border-border hover:bg-secondary/80"
                }`}
              >
                {tag}
              </button>
            ))}
          </div>
        )}

        <DataTable
          loading={loading}
          skeleton={<div className="p-5 space-y-3">{[1,2,3].map(i => <div key={i} className="h-14 rounded-lg border bg-muted/30 animate-pulse" />)}</div>}
          empty={
            <EmptyState
              icon={Database}
              title="Sin fuentes de datos"
              description="Agrega un archivo o URL para comenzar"
              action={can(PERM.KNOWLEDGE_UPDATE) ? (
                <Button variant="outline" size="sm" onClick={() => setPanelOpen(true)} className="gap-1.5">
                  <Plus className="w-3.5 h-3.5" /> Agregar
                </Button>
              ) : undefined}
              className="py-16"
            />
          }
          pagination={{ page, pageSize, total: filtered.length, onPageChange: setPage, onPageSizeChange: (n) => { setPageSize(n); setPage(1); } }}
          columns={[
            { id: "fuente", header: "Fuente" },
            { id: "estado", header: "Estado", className: "w-24", hideBelow: "sm" },
            { id: "revision", header: "Revisión", className: "w-28", hideBelow: "sm" },
            { id: "chunks", header: "Chunks", className: "w-24", hideBelow: "md" },
            { id: "etiquetas", header: "Etiquetas", className: "w-56", hideBelow: "lg" },
            { id: "acciones", header: "Acciones", className: "w-16 text-right", sticky: true },
          ]}
          data={paginated}
          rowKey={(s) => s.id}
          renderRow={(s) => (
            <SourceRow
              source={s}
              reviewing={reviewing}
              onReingest={handleReingest}
              onDelete={handleDelete}
              onApprove={handleApprove}
              onReject={handleReject}
              onUpdated={load}
            />
          )}
        />
      </Card>
      {/* Reject reason dialog */}
      <Modal
        open={!!rejectModal}
        onClose={() => { if (!rejectModal?.saving) setRejectModal(null); }}
        size="md"
        title={
          <span className="flex items-center gap-2">
            <XCircle className="w-4 h-4 text-destructive" />
            Rechazar fuente
          </span>
        }
        footer={
          <>
            <Button
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={() => setRejectModal(null)}
              disabled={rejectModal?.saving}
            >
              <X className="w-3.5 h-3.5" /> Cancelar
            </Button>
            <Button
              size="sm"
              variant="destructive"
              onClick={submitReject}
              disabled={!rejectModal?.reason.trim() || rejectModal?.saving}
              className="gap-1.5"
            >
              {rejectModal?.saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <XCircle className="w-3.5 h-3.5" />}
              Rechazar
            </Button>
          </>
        }
      >
        <div className="space-y-4 pt-1">
 <p className="text-13 text-muted-foreground">
             ¿Por qué rechazas <span className="font-semibold text-foreground">&ldquo;{rejectModal?.source.name}&rdquo;</span>?
             El motivo quedará registrado y el admin podrá revisarla luego.
           </p>
          <Textarea
            rows={3}
            placeholder="Ej: Contenido desactualizado, no corresponde a la fuente oficial..."
            value={rejectModal?.reason ?? ""}
            onChange={(e) => setRejectModal((m) => m ? { ...m, reason: e.target.value } : null)}
            className="resize-none"
          />
        </div>
      </Modal>
    </div>
  );
}

const TabLoading = () => <div className="space-y-4 py-8">{[1,2,3].map(i => <Skeleton key={i} className="h-16 w-full" />)}</div>;
const FAQTab = dynamic(
  () => import("./_components/FAQTab").catch(
    () => {
      const FAQFallback = () => (
        <div className="py-12 text-center text-muted-foreground">FAQ no disponible</div>
      );
      return FAQFallback;
    }
  ),
  { loading: TabLoading }
);

const TAB_IDS = ["sources", "faq"] as const;
type TabId = typeof TAB_IDS[number];

export default function SourcesPage() {
  const searchParams = useSearchParams();
  const initialTab = useMemo<TabId>(() => {
    const t = searchParams.get("tab");
    return TAB_IDS.includes(t as TabId) ? (t as TabId) : "sources";
  }, [searchParams]);
  const [tab, setTab] = useState<TabId>(initialTab);
  useEffect(() => { setTab(initialTab); }, [initialTab]);

  return (
    <div>
      <PageHeader
        icon={Database}
        title="Documentos"
        tip="Fuentes de datos y FAQ que alimentan al chatbot."
      />
      <Tabs value={tab} onValueChange={(v) => setTab(v as TabId)}>
        <div className="overflow-x-auto -mx-2 px-2">
          <TabsList className="mb-6">
            <TabsTrigger value="sources">Fuentes</TabsTrigger>
            <TabsTrigger value="faq">FAQ</TabsTrigger>
          </TabsList>
        </div>

        <TabsContent value="sources"><SourcesListContent /></TabsContent>
        <TabsContent value="faq"><FAQTab /></TabsContent>
      </Tabs>
    </div>
  );
}
