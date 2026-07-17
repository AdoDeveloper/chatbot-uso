"use client";

import { useEffect, useMemo, useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import {
 AlertTriangle, ArrowLeft, Ban, Clock, Copy, Edit3, Eye, History, Layers, Loader2,
 MoreHorizontal, RotateCcw, Save, Search, ShieldAlert, X,
} from "lucide-react";
import api from "@/lib/api";

import {
 DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { usePermission } from "@/hooks/use-permission";
import { PERM } from "@/lib/permissions";
import { useToast } from "@/components/ui/toast";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { PageShell } from "@/components/ui/page-shell";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { TablePagination } from "@/components/composed/table-pagination";
import { Modal } from "@/components/composed/modal";
import { Loading } from "@/components/ui/loading";
import { formatInProjectTz } from "@/lib/datetime";

type WarningFlag = "short" | "long" | "pii";

interface ChunkOut {
 id: string;
 text: string;
 source_id: string;
 source_name: string;
 chunk_index: number;
 section: string | null;
 parent_id: string | null;
 parent_text: string | null;
 warnings: WarningFlag[];
 is_discarded: boolean;
 was_edited: boolean;
}

interface ChunkListResponse {
 chunks: ChunkOut[];
 total: number;
 page: number;
 page_size: number;
 warning_counts: Record<string, number>;
}

interface ChunkEditOut {
 id: string;
 chunk_point_id: string;
 previous_content: string;
 new_content: string;
 edited_by_name: string | null;
 reason: string | null;
 edited_at: string;
}

const WARNING_LABEL: Record<WarningFlag, { label: string; cls: string; icon: typeof AlertTriangle }> = {
 short: { label: "muy corto",     icon: AlertTriangle, cls: "bg-warning/5 text-warning border-warning/20" },
 long: { label: "muy largo",     icon: AlertTriangle, cls: "bg-warning/5 text-warning border-warning/20" },
 pii:  { label: "PII detectado",   icon: ShieldAlert,  cls: "bg-destructive/5 text-destructive border-destructive/20" },
};

export default function SourceChunksPage() {
 const params = useParams();
 const sourceId = params.id as string;
  const { toast } = useToast();
 const can = usePermission();

 const [page, setPage] = useState(1);
 const [pageSize, setPageSize] = useState(20);
 const [expanded, setExpanded] = useState<string | null>(null);
 const [warningFilter, setWarningFilter] = useState<WarningFlag | "">("");
 const [editingChunk, setEditingChunk] = useState<ChunkOut | null>(null);
 const [busyChunk, setBusyChunk] = useState<string | null>(null);
 const [historyChunk, setHistoryChunk] = useState<ChunkOut | null>(null);
 const [previewChunk, setPreviewChunk] = useState<ChunkOut | null>(null);
 // Local full-text filter over the current page. For search across the
 // whole knowledge base use /dashboard/conocimiento/consulta (semantic retrieval).
 const [search, setSearch] = useState("");

 async function copyId(id: string) {
  try {
   await navigator.clipboard.writeText(id);
   toast({ type: "success", message: "ID del chunk copiado." });
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo copiar.") });
  }
 }

 const chunksQuery = useMemo(() => {
  const qs = new URLSearchParams({ page: String(page), page_size: String(pageSize) });
  if (warningFilter) qs.set("warning", warningFilter);
  return qs.toString();
 }, [page, pageSize, warningFilter]);

 // Reiniciar a la primera página al cambiar el filtro: la página actual
 // puede no existir en el nuevo subconjunto filtrado de chunks.
 useEffect(() => {
  setPage(1);
 }, [warningFilter]);

 const { data, loading, error: chunksError, refetch: load, setData } =
  useApi<ChunkListResponse>(`/chunks/source/${sourceId}?${chunksQuery}`);

 useEffect(() => {
  if (chunksError) toast({ type: "error", message: "No se pudieron cargar los chunks de esta fuente." });
 }, [chunksError, toast]);

 async function toggleDiscard(chunk: ChunkOut) {
  const target = chunk.is_discarded ? "restore" : "discard";
  setBusyChunk(chunk.id);
  try {
   await api.post<ChunkOut>(`/chunks/${chunk.id}/${target}`);
   setData((prev) => prev
    ? { ...prev, chunks: prev.chunks.map((c) => c.id === chunk.id ? { ...c, is_discarded: !chunk.is_discarded } : c) }
    : prev);
   toast({ type: "success", message: chunk.is_discarded ? "Chunk restaurado." : "Chunk descartado." });
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo actualizar el chunk.") });
  } finally {
   setBusyChunk(null);
  }
 }

 const totalWarnings = Object.values(data?.warning_counts ?? {}).reduce((a, b) => a + b, 0);

 // Local text filter over the current page only. Matches against the chunk
 // body, the section header, and the chunk id (so admins can paste a Qdrant
 // point id and locate it). Case-insensitive.
 const filteredChunks = data?.chunks
  ? data.chunks.filter((c) => {
     if (!search.trim()) return true;
     const needle = search.toLowerCase();
     return (
      c.text.toLowerCase().includes(needle) ||
      (c.section ?? "").toLowerCase().includes(needle) ||
      c.id.toLowerCase().includes(needle)
     );
    })
  : [];

 return (
  <PageShell
   icon={Layers}
   title="Chunks indexados"
   description={
     (data ? `${data.total} chunks en esta fuente` : "Cargando...") +
     (data?.chunks?.[0]?.source_name ? ` — ${data.chunks[0].source_name}` : "")
   }
   before={
     <Link
      href="/dashboard/conocimiento/documentos"
      className="inline-flex items-center gap-1.5 text-2xs text-muted-foreground hover:text-foreground mb-3 font-medium"
     >
      <ArrowLeft className="h-3 w-3" /> Base de conocimiento
     </Link>
   }
  >
   {loading ? (
    <Card>
     <CardContent className="py-6 space-y-3">
      {[1, 2, 3, 4, 5].map((i) => <Skeleton key={i} className="h-14 w-full" />)}
     </CardContent>
    </Card>
   ) : !data || data.chunks.length === 0 ? (
    <Card>
     <CardContent>
      <EmptyState
       icon={Layers}
       title={warningFilter ? "Sin chunks que coincidan" : "Sin chunks"}
       description={warningFilter
        ? "Ningún chunk tiene esa advertencia. Limpia el filtro para ver todos."
        : "Este documento aún no ha sido indexado"}
      />
     </CardContent>
    </Card>
   ) : (
    <Card className="overflow-hidden">
     <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-5 py-4 border-b border-border/60">
      <div className="relative w-full sm:w-72">
       <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground pointer-events-none" aria-hidden="true" />
       <Input
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        placeholder="Buscar en página actual..."
        aria-label="Buscar en chunks de la página actual"
        className="pl-8 h-9"
       />
      </div>
      {search.trim() && data && (
       <p className="text-2xs text-muted-foreground">
        {filteredChunks.length} de {data.chunks.length} coinciden.
        {" "}<Link href="/dashboard/conocimiento/consulta" className="text-primary hover:underline">
         Buscar en toda la base
        </Link>
       </p>
      )}
     </div>

     {/* Warnings summary banner */}
     {totalWarnings > 0 && (
      <div className="flex flex-wrap items-center gap-2 px-5 pt-4">
       <AlertTriangle className="h-4 w-4 text-warning shrink-0" />
       <span className="text-13 font-medium text-warning">
        {totalWarnings} {totalWarnings === 1 ? "chunk necesita" : "chunks necesitan"} atención:
       </span>
       <div className="flex gap-1.5 flex-wrap">
        {(Object.entries(data.warning_counts) as [WarningFlag, number][]).map(([k, n]) => {
         const w = WARNING_LABEL[k];
         if (!w) return null;
         const Icon = w.icon;
         const active = warningFilter === k;
         return (
          <button
           key={k}
           onClick={() => setWarningFilter(active ? "" : k)}
           className={`inline-flex items-center gap-1 text-2xs px-2 py-0.5 rounded-full border font-medium transition ${
            active
             ? "bg-warning text-white border-warning"
             : "bg-background text-warning border-warning/40 hover:bg-warning/10"
           }`}
          >
           <Icon className="w-3.5 h-3.5" />
           {w.label}: {n}
          </button>
         );
        })}
        {warningFilter && (
         <button
          onClick={() => setWarningFilter("")}
          className="inline-flex items-center gap-1 text-2xs px-2 py-0.5 rounded-full border bg-background text-muted-foreground border-border hover:bg-muted"
         >
          <X className="w-3 h-3" /> Limpiar filtro
         </button>
        )}
       </div>
      </div>
     )}

     <div className="overflow-x-auto mt-4">
       <Table>
        <TableHeader>
         <TableRow className="bg-muted/50">
          <TableHead className="w-14">#</TableHead>
          <TableHead className="w-28 hidden lg:table-cell">ID</TableHead>
          <TableHead className="w-40 hidden md:table-cell">Sección</TableHead>
          <TableHead>Texto</TableHead>
          <TableHead className="w-28 hidden sm:table-cell">Estado</TableHead>
          <TableHead className="w-36 hidden sm:table-cell">Alertas</TableHead>
          <TableHead className="w-14 text-right" sticky>Acciones</TableHead>
         </TableRow>
        </TableHeader>
       <TableBody>
        {filteredChunks.length === 0 && search.trim() ? (
         <TableRow>
          <TableCell colSpan={7} className="text-center py-8 text-sm text-muted-foreground">
           Ningún chunk de esta página coincide con &ldquo;{search}&rdquo;.
          </TableCell>
         </TableRow>
        ) : filteredChunks.map((chunk) => {
         const isExpanded = expanded === chunk.id;
         const isBusy = busyChunk === chunk.id;
         const charCount = chunk.text.length;
         // Truncate the Qdrant point id for compact display. Full id is
         // available via the copy button — useful when an admin needs to
         // reference a specific chunk in logs or tickets.
         const shortId = chunk.id.length > 12 ? `${chunk.id.slice(0, 6)}…${chunk.id.slice(-4)}` : chunk.id;
         return (
          <TableRow key={chunk.id} className={`group ${chunk.is_discarded ? "opacity-60" : ""}`}>
           <TableCell className="align-top">
            <Badge variant="secondary" className="font-mono text-xs">{chunk.chunk_index}</Badge>
           </TableCell>
           <TableCell className="align-top hidden lg:table-cell">
            <button
             type="button"
             onClick={() => copyId(chunk.id)}
             title={`ID Qdrant: ${chunk.id} (clic para copiar)`}
             className="inline-flex items-center gap-0.5 py-1 -my-1 text-3xs font-mono text-muted-foreground hover:text-foreground transition rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50"
             aria-label={`Copiar ID del chunk ${shortId}`}
            >
             <Copy className="w-3 h-3" aria-hidden="true" />
             {shortId}
            </button>
           </TableCell>
           <TableCell className="text-2xs text-muted-foreground truncate max-w-40 align-top hidden md:table-cell">
            {chunk.section || "—"}
           </TableCell>
           <TableCell className="align-top">
            <p
             className={`text-sm ${isExpanded ? "whitespace-pre-wrap" : "line-clamp-2"} cursor-pointer`}
             onClick={() => setExpanded(isExpanded ? null : chunk.id)}
            >
             {chunk.text}
            </p>
            <div className="flex items-center gap-2 mt-1.5">
             <span
              className="text-3xs tabular-nums text-muted-foreground"
              title={`${charCount} caracteres`}
             >
              {charCount.toLocaleString()} chars
             </span>
            </div>
            {isExpanded && chunk.parent_text && (
             <div className="mt-3 rounded-lg bg-muted p-3 text-xs border border-border">
              <span className="font-medium text-muted-foreground uppercase tracking-wider text-3xs">Contexto padre:</span>
              <p className="mt-1 text-muted-foreground whitespace-pre-wrap">{chunk.parent_text}</p>
             </div>
            )}
           </TableCell>
            <TableCell className="hidden sm:table-cell">
             {chunk.is_discarded ? (
              <Badge variant="outline" className="text-3xs bg-muted shrink-0">
               <Ban className="w-3 h-3 mr-1" /> descartado
              </Badge>
             ) : chunk.was_edited ? (
              <Badge variant="outline" className="text-3xs shrink-0">
               <Edit3 className="w-3 h-3 mr-1" /> editado
              </Badge>
             ) : (
              <span className="text-3xs text-muted-foreground">—</span>
             )}
            </TableCell>
            <TableCell className="hidden sm:table-cell">
             {chunk.warnings.length > 0 ? (
              <div className="flex flex-nowrap gap-1">
               {chunk.warnings.map((w) => {
                const meta = WARNING_LABEL[w];
                if (!meta) return null;
                const Icon = meta.icon;
                return (
                 <span
                  key={w}
                  className={`inline-flex items-center gap-0.5 text-3xs px-1.5 py-0.5 rounded border font-medium shrink-0 ${meta.cls}`}
                 >
                  <Icon className="w-3.5 h-3.5" /> {meta.label}
                 </span>
                );
               })}
              </div>
             ) : (
              <span className="text-3xs text-muted-foreground">—</span>
             )}
            </TableCell>
            <TableCell sticky className="text-right">
             <DropdownMenu>
              <DropdownMenuTrigger asChild>
               <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground">
                <MoreHorizontal className="w-4 h-4" />
               </Button>
              </DropdownMenuTrigger>
               <DropdownMenuContent align="end" className="w-44">
                <DropdownMenuItem onClick={() => setPreviewChunk(chunk)}>
                 <Eye className="w-3.5 h-3.5 mr-2" />
                 Vista previa
                </DropdownMenuItem>
                <DropdownMenuItem onClick={() => setHistoryChunk(chunk)} disabled={!chunk.was_edited}>
                 <History className="w-3.5 h-3.5 mr-2" />
                 Ver historial
                </DropdownMenuItem>
               {can(PERM.KNOWLEDGE_UPDATE) && (
                <>
                 <DropdownMenuItem onClick={() => setEditingChunk(chunk)}>
                  <Edit3 className="w-3.5 h-3.5 mr-2" />
                  Editar contenido
                 </DropdownMenuItem>
                 <DropdownMenuItem onClick={() => toggleDiscard(chunk)} disabled={isBusy}>
                  {isBusy
                   ? <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />
                   : chunk.is_discarded
                    ? <RotateCcw className="w-3.5 h-3.5 mr-2" />
                    : <Ban className="w-3.5 h-3.5 mr-2" />}
                  {chunk.is_discarded ? "Restaurar" : "Descartar"}
                 </DropdownMenuItem>
                </>
               )}
              </DropdownMenuContent>
             </DropdownMenu>
            </TableCell>
          </TableRow>
         );
        })}
       </TableBody>
      </Table>
     </div>

     <TablePagination
      total={data.total}
      page={page}
      pageSize={pageSize}
      onPageChange={setPage}
      onPageSizeChange={(n) => { setPageSize(n); setPage(1); }}
      itemLabel={warningFilter ? "chunks (filtro activo)" : "chunks"}
     />
    </Card>
   )}

   {/* Edit dialog */}
   <ChunkEditDialog
    chunk={editingChunk}
    onClose={() => setEditingChunk(null)}
    onSaved={() => { setEditingChunk(null); load(); }}
   />

   {/* History drawer */}
   <ChunkHistorySheet
    chunk={historyChunk}
    onClose={() => setHistoryChunk(null)}
   />

   {/* Preview modal */}
   <Modal
    open={!!previewChunk}
    onClose={() => setPreviewChunk(null)}
    title={`Chunk #${previewChunk?.chunk_index}`}
    size="3xl"
    subtitle={previewChunk ? `${previewChunk.text.length.toLocaleString()} caracteres` : undefined}
    footer={
     <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setPreviewChunk(null)}>
      <X className="w-3.5 h-3.5" /> Cerrar
     </Button>
    }
   >
    <pre className="text-sm whitespace-pre-wrap font-mono leading-relaxed">
     {previewChunk?.text}
    </pre>
   </Modal>
  </PageShell>
 );
}


function ChunkEditDialog({
 chunk,
 onClose,
 onSaved,
}: {
 chunk: ChunkOut | null;
 onClose: () => void;
 onSaved: () => void;
}) {
 const { toast } = useToast();
 const [text, setText] = useState("");
 const [reason, setReason] = useState("");
 const [saving, setSaving] = useState(false);

 useEffect(() => {
  if (chunk) {
   setText(chunk.text);
   setReason("");
  }
 }, [chunk]);

 const open = !!chunk;
 const modified = chunk ? text.trim() !== chunk.text.trim() : false;

 async function save() {
  if (!chunk || !modified) return;
  setSaving(true);
  try {
   await api.patch(`/chunks/${chunk.id}/content`, { text, reason: reason.trim() || undefined });
   toast({ type: "success", message: "Chunk editado y re-indexado." });
   onSaved();
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar.") });
  } finally {
   setSaving(false);
  }
 }

  return (
   <Modal
    open={open}
    onClose={onClose}
    title={`Editar chunk #${chunk?.chunk_index}`}
    size="3xl"
    footer={
     <>
      <Button variant="outline" size="sm" className="gap-1.5" onClick={onClose}><X className="w-3.5 h-3.5" /> Cancelar</Button>
      <Button size="sm" onClick={save} disabled={!modified || saving} className="gap-1.5">
       {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
       Re-indexar
      </Button>
     </>
    }
   >
    <div className="space-y-4 h-full flex flex-col">
     <div className="flex-1 flex flex-col min-h-0">
      <label className="text-xs font-medium text-muted-foreground mb-1 block">Contenido</label>
      <textarea
       value={text}
       onChange={(e) => setText(e.target.value)}
       className="flex-1 min-h-[150px] w-full px-3 py-2.5 bg-background border border-input rounded-md text-sm font-mono resize-y focus:outline-none focus:ring-2 focus:ring-ring/50 leading-relaxed"
      />
      <p className="text-2xs text-muted-foreground mt-1 tabular-nums">{text.length.toLocaleString()} caracteres</p>
     </div>
     <div>
      <label className="text-xs font-medium text-muted-foreground mb-1 block">
       Razón del cambio <span className="font-normal">(opcional)</span>
      </label>
      <input
       value={reason}
       onChange={(e) => setReason(e.target.value)}
       placeholder="Ej: normalización de mayúsculas, corregí el teléfono..."
       className="w-full h-9 px-3 bg-background border border-input rounded-md text-sm focus:outline-none focus:ring-2 focus:ring-ring/50"
      />
     </div>
     <div className="rounded-lg bg-muted/50 border border-border p-3 text-2xs text-muted-foreground">
      <strong>Al guardar:</strong> se regenera el embedding, se recomputan los warnings,
      se invalida el caché y se registra en el historial.
     </div>
    </div>
   </Modal>
  );
}


function ChunkHistorySheet({
 chunk,
 onClose,
}: {
 chunk: ChunkOut | null;
 onClose: () => void;
}) {
 const { toast } = useToast();
 const { data: historyData, loading: firstLoading, refetching, error: historyError } =
  useApi<ChunkEditOut[]>(chunk ? `/chunks/${chunk.id}/history` : null, [chunk?.id]);
 const history = historyError ? [] : (historyData ?? []);
 // El diálogo se abre varias veces con chunks distintos: mostrar "Cargando..."
 // también en recargas para no enseñar el historial del chunk anterior.
 const loading = firstLoading || refetching;

 useEffect(() => {
  if (historyError) toast({ type: "error", message: "No se pudo cargar el historial de ediciones." });
 }, [historyError, toast]);

 const open = !!chunk;

  return (
   <Modal
    open={open}
    onClose={onClose}
    title="Historial de ediciones"
    subtitle={chunk ? `Chunk #${chunk.chunk_index} · ${chunk.id.slice(0, 8)}` : undefined}
    size="2xl"
   >
    <div className="space-y-4">
     {loading ? (
      <Loading />
     ) : history.length === 0 ? (
      <EmptyState icon={Clock} title="Sin ediciones" description="Este chunk nunca ha sido modificado." />
     ) : (
      history.map((edit) => (
       <div key={edit.id} className="rounded-lg border border-border bg-card p-4 space-y-3">
        <div className="flex items-center justify-between gap-2 text-xs">
         <div className="flex items-center gap-1.5 text-muted-foreground">
          <Clock className="w-3 h-3" />
          <time className="tabular-nums">
           {formatInProjectTz(edit.edited_at, {
            day: "2-digit", month: "short", year: "numeric",
            hour: "2-digit", minute: "2-digit",
           })}
          </time>
         </div>
         <span className="font-medium text-foreground">{edit.edited_by_name ?? "Sistema"}</span>
        </div>
        {edit.reason && (
          <p className="text-xs italic text-muted-foreground">&quot;{edit.reason}&quot;</p>
        )}
        <div className="space-y-2">
         <div>
          <p className="text-3xs uppercase tracking-wider text-muted-foreground font-medium mb-1">Antes</p>
          <div className="bg-destructive/5 border border-destructive/20 rounded px-2 py-1.5 text-xs whitespace-pre-wrap max-h-40 overflow-y-auto">
           {edit.previous_content}
          </div>
         </div>
         <div>
          <p className="text-3xs uppercase tracking-wider text-muted-foreground font-medium mb-1">Después</p>
          <div className="bg-success/10 border border-success/40 rounded px-2 py-1.5 text-xs whitespace-pre-wrap max-h-40 overflow-y-auto">
           {edit.new_content}
          </div>
         </div>
        </div>
       </div>
      ))
     )}
    </div>
   </Modal>
  );
 }
