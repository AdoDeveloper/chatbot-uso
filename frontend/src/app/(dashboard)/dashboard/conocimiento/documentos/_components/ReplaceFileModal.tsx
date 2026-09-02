"use client";

import { useEffect, useRef, useState } from "react";
import { Upload, Loader2, RefreshCw, X } from "lucide-react";
import api from "@/lib/api";
import { getErrorMessage, invalidateApiCache, useApi } from "@/hooks/use-api";
import { Button } from "@/components/ui/button";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Modal } from "@/components/composed/modal";
import { useToast } from "@/components/ui/toast";
import type { Source } from "@/types";
import { fmtSize } from "./sources-helpers";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".txt"];

export function ReplaceFileModal({ source, onClose, onReplaced }: {
  source: Source | null; onClose: () => void; onReplaced: () => void;
}) {
  const { toast } = useToast();
  const [file, setFile] = useState<File | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const { data: uploadLimits } = useApi<{ source_mb: number }>("/sources/upload-limits");
  const sourceMb = uploadLimits?.source_mb ?? 50;

  useEffect(() => {
    if (!source) { setFile(null); setError(null); }
  }, [source]);

  function acceptFile(f: File) {
    if (!ACCEPTED_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext))) {
      setError(`Tipo de archivo no soportado. Use ${ACCEPTED_EXTENSIONS.join(", ")}.`);
      return;
    }
    const maxBytes = sourceMb * 1024 * 1024;
    if (f.size > maxBytes) {
      setError(`El archivo excede el límite de ${sourceMb} MB.`);
      return;
    }
    setError(null);
    setFile(f);
  }

  const handleSubmit = async () => {
    if (!source || !file) return;
    setSubmitting(true);
    setError(null);
    try {
      const formData = new FormData();
      formData.append("file", file);
      invalidateApiCache("/sources");
      await api.post(`/sources/${source.id}/replace-file`, formData, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      toast({ type: "success", message: "Archivo reemplazado. La fuente vuelve a revisión." });
      onReplaced();
      onClose();
    } catch (err: unknown) {
      setError(getErrorMessage(err, "No se pudo reemplazar el archivo."));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      open={!!source}
      onClose={() => { if (!submitting) onClose(); }}
      size="md"
      title={
        <span className="flex items-center gap-2">
          <RefreshCw className="w-4 h-4 text-primary" />
          Reemplazar archivo
        </span>
      }
      footer={
        <>
          <Button variant="outline" size="sm" className="gap-1.5" onClick={onClose} disabled={submitting}>
            <X className="w-3.5 h-3.5" /> Cancelar
          </Button>
          <Button size="sm" className="gap-1.5" onClick={handleSubmit} disabled={!file || submitting}>
            {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Upload className="w-3.5 h-3.5" />}
            {submitting ? "Subiendo..." : "Reemplazar"}
          </Button>
        </>
      }
    >
      <div className="space-y-4 pt-1">
        <p className="text-13 text-muted-foreground">
          Suba un nuevo archivo para <span className="font-semibold text-foreground">&ldquo;{source?.name}&rdquo;</span>.
          El contenido anterior se descarta y la fuente vuelve a revisión pendiente.
        </p>

        {error && (
          <Alert variant="destructive">
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_EXTENSIONS.join(",")}
          className="hidden"
          onChange={(e) => { if (e.target.files?.[0]) acceptFile(e.target.files[0]); e.target.value = ""; }}
        />

        {file ? (
          <div className="flex items-center justify-between gap-3 rounded-lg border border-border bg-muted/30 px-3 py-2.5">
            <div className="min-w-0">
              <p className="text-13 font-medium text-foreground truncate">{file.name}</p>
              <p className="text-2xs text-muted-foreground">{fmtSize(file.size)}</p>
            </div>
            <Button variant="ghost" size="icon-xs" onClick={() => setFile(null)} disabled={submitting}>
              <X className="w-3.5 h-3.5" />
            </Button>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => fileInputRef.current?.click()}
            className="w-full flex flex-col items-center justify-center gap-2 rounded-lg border-2 border-dashed border-border py-8 text-muted-foreground hover:border-primary hover:text-primary transition"
          >
            <Upload className="w-5 h-5" />
            <span className="text-13">Haga clic para seleccionar un archivo</span>
            <span className="text-2xs">{ACCEPTED_EXTENSIONS.join(", ")} · máx. {sourceMb} MB</span>
          </button>
        )}
      </div>
    </Modal>
  );
}
