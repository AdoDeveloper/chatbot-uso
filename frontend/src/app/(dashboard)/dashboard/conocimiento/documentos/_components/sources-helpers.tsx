"use client";

import { useState } from "react";
import {
  FileText, BookOpen, Loader2, FileSearch, Scissors, Eraser, Brain,
  CheckCheck, Ban, Clock, X,
} from "lucide-react";
import api from "@/lib/api";
import type { Source } from "@/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export const TYPE_ICON: Record<string, React.ElementType> = {
  pdf: FileText, docx: FileText, xlsx: FileText,
  csv: FileText, txt: FileText, faq: BookOpen,
};

export const TYPE_LABEL: Record<string, string> = {
  pdf: "PDF", docx: "Word", xlsx: "Excel",
  csv: "CSV", txt: "TXT", faq: "FAQ",
};

export const STATUS_BADGE: Record<string, string> = {
  ready: "bg-brand-green/15 text-brand-green",
  processing: "bg-primary/10 text-primary",
  pending: "text-warning",
  error: "bg-destructive/10 text-destructive",
};

export const STATUS_LABEL: Record<string, string> = {
  ready: "Listo", processing: "Procesando", pending: "Pendiente", error: "Error",
};

type ReviewBadge = { label: string; className: string; icon: typeof Clock };

export const REVIEW_BADGE: Record<string, ReviewBadge> = {
  procesando:         { label: "Procesando", icon: Loader2,    className: "bg-muted text-muted-foreground border-border" },
  pendiente_revision: { label: "Pendiente",  icon: Clock,      className: "text-warning border-warning/30" },
  aprobada:           { label: "Aprobada",   icon: CheckCheck, className: "bg-brand-green/10 text-brand-green border-brand-green/40" },
  rechazada:          { label: "Rechazada",  icon: Ban,        className: "bg-destructive/10 text-destructive border-destructive/20" },
};

export function fmtSize(bytes: number | null) {
  if (!bytes) return "—";
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

interface StageInfo { icon: React.ElementType; label: string; percent: number | null; }

export function parseStage(stage: string | null, sourceType: string): StageInfo {
  if (!stage || stage === "starting") return { icon: Loader2, label: "Iniciando...", percent: null };
  if (stage === "parsing") {
    const typeLabel: Record<string, string> = {
      pdf: "Extrayendo texto del PDF...",
      docx: "Leyendo documento Word...", xlsx: "Procesando hoja de cálculo...",
      csv: "Leyendo archivo CSV...", txt: "Leyendo archivo de texto...",
    };
    return { icon: FileSearch, label: typeLabel[sourceType] ?? "Extrayendo contenido...", percent: null };
  }
  if (stage === "chunking") return { icon: Scissors, label: "Dividiendo en fragmentos...", percent: null };
  if (stage === "cleaning") return { icon: Eraser, label: "Limpiando índice anterior...", percent: null };
  if (stage.startsWith("embedding:")) {
    const [, current, total] = stage.split(":");
    const cur = parseInt(current, 10);
    const tot = parseInt(total, 10);
    const pct = tot > 0 ? Math.round((cur / tot) * 100) : null;
    return { icon: Brain, label: `Generando embeddings (${cur}/${tot})...`, percent: pct };
  }
  return { icon: Loader2, label: "Procesando...", percent: null };
}

export function mergeSources(prev: Source[], next: Source[]): Source[] {
  let changed = prev.length !== next.length;
  const merged = next.map((n) => {
    const existing = prev.find((p) => p.id === n.id);
    if (existing && existing.updated_at === n.updated_at && existing.status === n.status && existing.progress_stage === n.progress_stage) {
      return existing;
    }
    changed = true;
    return n;
  });
  return changed ? merged : prev;
}

export function TagInput({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
  const [input, setInput] = useState("");
  const add = () => {
    const t = input.trim().toLowerCase();
    if (t && !value.includes(t)) onChange([...value, t]);
    setInput("");
  };
  return (
    <div>
      <div className="flex flex-wrap gap-1.5 mb-2">
        {value.map((tag) => (
          <span key={tag} className="flex items-center gap-1 px-2 py-0.5 bg-secondary text-secondary-foreground text-xs rounded-full border border-border">
            {tag}
            <button type="button" onClick={() => onChange(value.filter((t) => t !== tag))} aria-label={`Quitar etiqueta ${tag}`} className="hover:text-destructive rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50">
              <X className="w-3 h-3" aria-hidden="true" />
            </button>
          </span>
        ))}
      </div>
      <div className="flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); add(); } }}
          placeholder="Ej: admisiones, 2026..."
          className="h-8"
        />
        <Button type="button" variant="outline" size="sm" onClick={add}>+ Agregar</Button>
      </div>
    </div>
  );
}

export async function patchSourceTags(sourceId: string, tags: string[]) {
  await api.patch(`/sources/${sourceId}`, { tags });
}
