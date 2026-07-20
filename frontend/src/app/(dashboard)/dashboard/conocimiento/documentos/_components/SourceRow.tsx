"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  RefreshCw, Trash2, AlertCircle, Loader2, FileSearch,
  CheckCheck, Ban, Eye,
  MoreHorizontal, Save, X,
} from "lucide-react";
import type { Source, SourcePreview, SourceQuality } from "@/types";
import { Modal } from "@/components/composed/modal";
import {
  DropdownMenu, DropdownMenuContent, DropdownMenuItem,
  DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { TableCell, TableRow } from "@/components/ui/table";
import api from "@/lib/api";
import { getErrorMessage } from "@/hooks/use-api";
import {
  TYPE_LABEL, STATUS_BADGE, STATUS_LABEL, REVIEW_BADGE,
  TagInput, parseStage,
  patchSourceTags,
} from "./sources-helpers";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { usePermission } from "@/hooks/use-permission";
import { PERM } from "@/lib/permissions";
import { Loading } from "@/components/ui/loading";

function InlineTagEditor({ source, onUpdated }: { source: Source; onUpdated: () => void }) {
  const { toast } = useToast();
  const [editing, setEditing] = useState(false);
  const [tags, setTags] = useState<string[]>(source.tags ?? []);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (editing) setTags(source.tags ?? []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [editing]);

  const save = async () => {
    setSaving(true);
    try {
      await patchSourceTags(source.id, tags);
      onUpdated();
      setEditing(false);
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudieron guardar las etiquetas.") });
    } finally { setSaving(false); }
  };

  return (
    <>
      <div className="flex items-center gap-1.5 flex-wrap">
        {(source.tags ?? []).map((tag) => (
          <span key={tag} className="px-2 py-0.5 bg-primary/8 text-primary text-2xs rounded-full border border-primary/20">
            {tag}
          </span>
        ))}
        <button
          onClick={() => setEditing(true)}
          className="px-2 py-0.5 text-2xs text-muted-foreground border border-dashed border-border rounded-full hover:border-muted-foreground hover:text-foreground transition"
        >
          + Agregar
        </button>
      </div>

      <Modal
        open={editing}
        onClose={() => setEditing(false)}
        title="Etiquetas"
        size="md"
        footer={
          <>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setEditing(false)}>
              <X className="w-3.5 h-3.5" /> Cancelar
            </Button>
            <Button size="sm" className="gap-1.5" onClick={save} disabled={saving}>
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              {saving ? "Guardando..." : "Guardar"}
            </Button>
          </>
        }
      >
        <TagInput value={tags} onChange={setTags} />
      </Modal>
    </>
  );
}

export function SourceRow({
  source, reviewing, onReingest, onDelete, onApprove, onReject, onUpdated,
}: {
  source: Source;
  reviewing: string | null;
  onReingest: (s: Source) => void;
  onDelete: (s: Source) => void;
  onApprove: (s: Source) => void;
  onReject: (s: Source) => void;
  onUpdated: () => void;
}) {
  const router = useRouter();
  const can = usePermission();
  const isBusy = source.status === "processing" || source.status === "pending";
  const stage = isBusy ? parseStage(source.progress_stage, source.type) : null;

  const isError = source.status === "error";
  const isPending = source.review_status === "pendiente_revision" && source.status === "ready";
  const isReady = source.status === "ready";

  const [previewOpen, setPreviewOpen] = useState(false);
  const [preview, setPreview] = useState<SourcePreview | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [quality, setQuality] = useState<SourceQuality | null>(null);

  async function openPreview() {
    setPreviewOpen(true);
    setPreviewLoading(true);
    try {
      const [{ data: pv }, qResult] = await Promise.all([
        api.get<SourcePreview>(`/sources/${source.id}/preview?max_chars=4000`),
        api.get<SourceQuality>(`/sources/${source.id}/quality`).then(r => r.data).catch(() => null),
      ]);
      setPreview(pv);
      setQuality(qResult);
    } catch {
      setPreview({ preview: "", truncated: false, error: "No se pudo cargar la vista previa." });
    } finally {
      setPreviewLoading(false);
    }
  }

  const reviewBadge = REVIEW_BADGE[source.review_status];
  const errorTooltip = isError && source.error_message
    ? `${source.error_code ? `[${source.error_code}] ` : ""}${source.error_message}${source.error_hint ? ` — ${source.error_hint}` : ""}`
    : undefined;
  const rejectionTooltip = source.review_status === "rechazada" && source.rejection_reason
    ? `${source.rejection_reason}${source.reviewed_by_name ? ` (${source.reviewed_by_name})` : ""}`
    : undefined;

  return (
    <>
    <TableRow>
      <TableCell className="max-w-40 sm:max-w-none">
       <div className="flex items-center gap-1.5 min-w-0">
        <span className="font-semibold text-foreground text-13 truncate">{source.name}</span>
        <span className="text-3xs uppercase bg-muted text-muted-foreground px-1.5 py-0.5 rounded font-medium tracking-wide shrink-0">
         {TYPE_LABEL[source.type] ?? source.type}
        </span>
       </div>
      </TableCell>
     <TableCell className="hidden sm:table-cell">
      <div className="flex items-center gap-1.5">
       <span className={`text-3xs px-1.5 py-0.5 rounded-full font-medium whitespace-nowrap ${STATUS_BADGE[source.status]}`}>
        {STATUS_LABEL[source.status] ?? source.status}
       </span>
       {isBusy && stage && (
        <span className="text-3xs text-muted-foreground tabular-nums" title={stage.label}>
         {stage.percent !== null ? `${stage.percent}%` : "…"}
        </span>
       )}
      </div>
     </TableCell>
     <TableCell className="hidden sm:table-cell">
      {reviewBadge ? (() => {
       const ReviewIcon = reviewBadge.icon;
       return (
        <span
         className={`text-3xs px-1.5 py-0.5 rounded border font-medium inline-flex items-center gap-1 whitespace-nowrap ${reviewBadge.className}`}
         title={rejectionTooltip}
        >
         <ReviewIcon className={`w-3.5 h-3.5 ${source.review_status === "procesando" ? "animate-spin" : ""}`} />
         {reviewBadge.label}
        </span>
       );
      })() : <span className="text-3xs text-muted-foreground">—</span>}
     </TableCell>
     <TableCell className="hidden md:table-cell">
      <span className="tabular-nums text-13">{source.chunk_count.toLocaleString()}</span>
     </TableCell>
     <TableCell className="hidden lg:table-cell">
      <InlineTagEditor source={source} onUpdated={onUpdated} />
     </TableCell>
     <TableCell sticky>
      <div className="flex justify-end">
       <DropdownMenu>
        <DropdownMenuTrigger asChild>
         <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground">
          <MoreHorizontal className="w-4 h-4" />
         </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end" className="w-48">
         {can(PERM.KNOWLEDGE_MANAGE) && isPending && (
          <>
           <DropdownMenuItem onClick={() => onApprove(source)} disabled={reviewing === source.id}>
            {reviewing === source.id
             ? <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" />
             : <CheckCheck className="w-3.5 h-3.5 mr-2" />}
            Aprobar
           </DropdownMenuItem>
           <DropdownMenuItem onClick={() => onReject(source)} disabled={reviewing === source.id} className="text-destructive focus:text-destructive">
            <Ban className="w-3.5 h-3.5 mr-2" />
            Rechazar
           </DropdownMenuItem>
          </>
         )}
         {can(PERM.KNOWLEDGE_UPDATE) && isError && (
          <DropdownMenuItem onClick={() => onReingest(source)}>
           <RefreshCw className="w-3.5 h-3.5 mr-2" />
           Reingestar
          </DropdownMenuItem>
         )}
         <DropdownMenuItem onClick={openPreview}>
          <Eye className="w-3.5 h-3.5 mr-2" />
          Vista previa
         </DropdownMenuItem>
         {isReady && source.chunk_count > 0 && (
          <DropdownMenuItem onClick={() => router.push(`/dashboard/conocimiento/documentos/${source.id}/chunks`)}>
           <FileSearch className="w-3.5 h-3.5 mr-2" />
           Ver chunks
          </DropdownMenuItem>
         )}
         {errorTooltip && (
          <DropdownMenuItem disabled title={errorTooltip}>
           <AlertCircle className="w-3.5 h-3.5 mr-2" />
           Ver error
          </DropdownMenuItem>
         )}
         {can(PERM.KNOWLEDGE_UPDATE) && !isError && !isBusy && (
          <DropdownMenuItem onClick={() => onReingest(source)}>
           <RefreshCw className="w-3.5 h-3.5 mr-2" />
           Reingestar
          </DropdownMenuItem>
         )}
         {can(PERM.KNOWLEDGE_UPDATE) && (
          <>
           <DropdownMenuSeparator />
           <DropdownMenuItem
            onClick={() => onDelete(source)}
            className="text-destructive focus:text-destructive focus:bg-destructive/10"
           >
            <Trash2 className="w-3.5 h-3.5 mr-2" />
            Eliminar
           </DropdownMenuItem>
          </>
         )}
        </DropdownMenuContent>
       </DropdownMenu>
      </div>
     </TableCell>
    </TableRow>

    {/* Preview modal */}
      <Modal
        open={previewOpen}
        onClose={() => setPreviewOpen(false)}
        size="3xl"
        title={
          <span className="flex items-center gap-2">
            <Eye className="w-4 h-4 text-primary" />
            Vista previa — {source.name}
          </span>
        }
      >
        <div className="space-y-3 py-2">
          {quality && (
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-2">
              <div className="border border-border rounded-md px-3 py-2">
                <p className="text-3xs uppercase tracking-wider text-muted-foreground">Chunks</p>
                <p className="text-lg font-bold tabular-nums">{quality.total_chunks.toLocaleString()}</p>
              </div>
              <div className="border border-border rounded-md px-3 py-2">
                <p className="text-3xs uppercase tracking-wider text-muted-foreground">Hits 7d</p>
                <p className={`text-lg font-bold tabular-nums ${quality.hits_7d > 0 ? "text-success" : "text-muted-foreground"}`}>
                  {quality.hits_7d}
                </p>
              </div>
              <div className="border border-border rounded-md px-3 py-2">
                <p className="text-3xs uppercase tracking-wider text-muted-foreground">Último uso</p>
                <p className="text-xs font-medium tabular-nums mt-1">
                  {quality.last_used_at
                    ? new Date(quality.last_used_at).toLocaleDateString("es", { day: "2-digit", month: "short", year: "numeric" })
                    : "Nunca"}
                </p>
              </div>
            </div>
          )}
          <div>
            <p className="text-3xs uppercase tracking-wider text-muted-foreground font-semibold mb-1.5">Contenido extraído</p>
            {previewLoading ? (
              <Loading />
            ) : preview?.error ? (
              <div className="rounded-md border border-warning/30 bg-warning/5 px-3 py-2 text-xs text-warning-foreground">
                {preview.error}
              </div>
            ) : (
              <>
                <div className="rounded-md border border-border bg-muted/20 p-3 max-h-96 overflow-y-auto">
                  <pre className="text-xs whitespace-pre-wrap font-mono leading-relaxed overflow-x-auto">{preview?.preview || "(vacío)"}</pre>
                </div>
                {preview?.truncated && (
                  <p className="text-3xs text-muted-foreground mt-1 italic">Vista previa truncada a 4000 caracteres.</p>
                )}
              </>
            )}
          </div>
        </div>
      </Modal>
    </>
  );
}
