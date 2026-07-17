"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Upload, Loader2, AlertCircle, Save, X } from "lucide-react";
import api, { UPLOAD_LIMITS } from "@/lib/api";
import { getErrorMessage } from "@/hooks/use-api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Modal } from "@/components/composed/modal";
import { TagInput, fmtSize } from "./sources-helpers";

const ACCEPTED_EXTENSIONS = [".pdf", ".docx", ".xlsx", ".csv", ".txt"];

export function AddSourcePanel({ open, onClose, onCreated }: {
  open: boolean; onClose: () => void; onCreated: () => void;
}) {
  const [sourceName, setSourceName] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState<string[]>([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const [files, setFiles] = useState<File[]>([]);
  const [dragging, setDragging] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!open) {
      setFiles([]); setSourceName(""); setDescription(""); setTags([]);
      setError(null);
    }
  }, [open]);

  const acceptFiles = useCallback((incoming: FileList | File[]) => {
    const arr = Array.from(incoming);
    const invalid = arr.filter((f) => !ACCEPTED_EXTENSIONS.some((ext) => f.name.toLowerCase().endsWith(ext)));
    if (invalid.length) {
      setError(`${invalid.map((f) => f.name).join(", ")}: tipo de archivo no soportado. Use ${ACCEPTED_EXTENSIONS.join(", ")}.`);
      return;
    }
    const maxBytes = UPLOAD_LIMITS.source_mb * 1024 * 1024;
    const tooBig = arr.filter((f) => f.size > maxBytes);
    if (tooBig.length) {
      setError(`${tooBig.map((f) => f.name).join(", ")} excede el límite de ${UPLOAD_LIMITS.source_mb} MB.`);
      return;
    }
    setFiles((prev) => {
      const names = new Set(prev.map((f) => f.name));
      const merged = [...prev, ...arr.filter((f) => !names.has(f.name))];
      if (merged.length === 1 && !sourceName) setSourceName(merged[0].name.replace(/\.[^/.]+$/, ""));
      return merged;
    });
    setError(null);
  }, [sourceName]);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault(); setDragging(false);
    if (e.dataTransfer.files.length) acceptFiles(e.dataTransfer.files);
  }, [acceptFiles]);

  const handleSubmit = async () => {
    setError(null);
    if (files.length === 0) { setError("Seleccione al menos un archivo"); return; }
    if (files.length === 1 && !sourceName.trim()) { setError("Ingrese un nombre para la fuente"); return; }

    setSubmitting(true);
    try {
      if (files.length > 1) {
        // Bulk upload — names are derived from filenames
        const form = new FormData();
        files.forEach((f) => form.append("files", f));
        form.append("tags", JSON.stringify(tags));
        const res = await api.post<{ created: { id: string; name: string }[]; errors: { name: string; error: string }[] }>(
          "/sources/bulk-upload", form, { headers: { "Content-Type": "multipart/form-data" } }
        );
        const { created, errors: errs } = res.data;
        if (errs.length) {
          setError(`${errs.length} archivo(s) con error: ${errs.map((e) => e.name).join(", ")}`);
          if (created.length) { onCreated(); onClose(); }
        } else {
          onCreated(); onClose();
        }
        return;
      }
      // Single file with custom name/description
      const form = new FormData();
      form.append("file", files[0]);
      form.append("name", sourceName.trim());
      if (description.trim()) form.append("description", description.trim());
      form.append("tags", JSON.stringify(tags));
      await api.post("/sources/upload", form, { headers: { "Content-Type": "multipart/form-data" } });
      onCreated();
      onClose();
    } catch (err: unknown) {
      // El backend puede devolver `detail` como string o como objeto
      // estructurado (p. ej. 409 DUPLICATE_CONTENT: {code, message,
      // existing_id, existing_name}) — getErrorMessage extrae el `message`
      // del objeto para no inyectar un objeto crudo en el JSX.
      setError(getErrorMessage(err, "No se pudo crear la fuente"));
    } finally { setSubmitting(false); }
  };

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Nueva fuente de datos"
      size="3xl"
      footer={
        <div className="flex gap-3 w-full">
          <Button variant="outline" className="flex-1 gap-1.5" onClick={onClose}>
            <X className="w-3.5 h-3.5" /> Cancelar
          </Button>
          <Button
            className="flex-1 gap-1.5"
            onClick={handleSubmit}
            disabled={submitting || files.length === 0 || (files.length === 1 && !sourceName.trim())}
          >
            {submitting ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
            {submitting ? "Procesando..." : "Guardar"}
          </Button>
        </div>
      }
    >
      <div className="space-y-4">
        {error && (
          <Alert variant="destructive">
            <AlertCircle className="h-4 w-4" />
            <AlertDescription>{error}</AlertDescription>
          </Alert>
        )}

        <input ref={fileInputRef} type="file" accept={ACCEPTED_EXTENSIONS.join(",")} multiple className="hidden"
          onChange={(e) => { if (e.target.files?.length) acceptFiles(e.target.files); e.target.value = ""; }} />
        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Archivos</Label>
          <div
            onDragOver={(e) => { e.preventDefault(); setDragging(true); }}
            onDragLeave={() => setDragging(false)}
            onDrop={handleDrop}
            onClick={() => fileInputRef.current?.click()}
            className={`flex flex-col items-center justify-center gap-3 p-8 border-2 border-dashed rounded-xl cursor-pointer transition-colors ${
              dragging ? "border-primary bg-primary/5" : files.length > 0 ? "border-brand-green/40 bg-brand-green/10" : "border-border hover:border-primary/40 hover:bg-muted/50"
            }`}
          >
            <Upload className={`w-8 h-8 ${files.length > 0 ? "text-brand-green" : "text-muted-foreground/40"}`} />
            {files.length === 0 ? (
              <>
                <div className="text-center">
                  <p className="text-sm text-muted-foreground"><span className="font-semibold text-primary">Haga clic para seleccionar</span></p>
                  <p className="text-sm text-muted-foreground/60 mt-0.5">o arrastre los archivos aquí — puede seleccionar varios</p>
                </div>
                <p className="text-2xs text-muted-foreground bg-muted px-3 py-1 rounded-full">
                  PDF · DOCX · XLSX
                </p>
              </>
            ) : (
              <p className="text-13 font-medium text-center text-brand-green">
                {files.length} archivo{files.length > 1 ? "s" : ""} seleccionado{files.length > 1 ? "s" : ""}
              </p>
            )}
          </div>
          {files.length > 0 && (
            <ul className="space-y-1 mt-1">
              {files.map((f, i) => (
                <li key={f.name} className="flex items-center justify-between text-xs bg-muted/50 rounded-lg px-3 py-1.5">
                  <span className="truncate max-w-70 font-medium">{f.name}</span>
                  <span className="text-muted-foreground ml-2 shrink-0">{fmtSize(f.size)}</span>
                  <button
                    type="button"
                    onClick={(e) => { e.stopPropagation(); setFiles((prev) => prev.filter((_, j) => j !== i)); }}
                    className="ml-2 text-muted-foreground hover:text-destructive transition shrink-0"
                  >
                    <X className="w-3 h-3" />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Nombre de la fuente</Label>
          <Input
            value={sourceName} onChange={(e) => setSourceName(e.target.value)}
            placeholder="Ej: Instructivo para alumnos 2026"
          />
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Descripción <span className="normal-case font-normal text-muted-foreground">(opcional)</span>
          </Label>
          <textarea
            value={description} onChange={(e) => setDescription(e.target.value)}
            rows={2} placeholder="Breve descripción del contenido de esta fuente..."
            className="w-full px-3 py-2 bg-background border border-input rounded-md text-sm resize-none focus:outline-none focus:ring-2 focus:ring-ring/50 focus:border-ring placeholder:text-muted-foreground"
          />
        </div>

        <div className="space-y-1.5">
          <Label className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Etiquetas <span className="normal-case font-normal text-muted-foreground">(opcional)</span>
          </Label>
          <TagInput value={tags} onChange={setTags} />
        </div>
      </div>
    </Modal>
  );
}
