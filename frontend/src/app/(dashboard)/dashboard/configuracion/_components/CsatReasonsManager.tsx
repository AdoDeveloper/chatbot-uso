"use client";

import { useState } from "react";
import { GripVertical, Loader2, Plus, Trash2 } from "lucide-react";

import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

interface CsatReason {
  id: string;
  label: string;
  enabled: boolean;
}

export function CsatReasonsManager() {
  const { data, loading, error, setData } = useApi<CsatReason[]>("/widget/csat-reasons");
  const { toast, confirm } = useToast();
  const [newLabel, setNewLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editingLabel, setEditingLabel] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [draggedId, setDraggedId] = useState<string | null>(null);

  async function handleCreate() {
    const label = newLabel.trim();
    if (!label) return;
    setCreating(true);
    try {
      const { data: created } = await api.post<CsatReason>("/widget/csat-reasons", { label });
      setData((prev) => [...(prev ?? []), created]);
      setNewLabel("");
      toast({ type: "success", message: "Motivo creado." });
    } catch (err) {
      toast({ type: "error", title: "No se pudo crear el motivo", message: getErrorMessage(err) });
    } finally {
      setCreating(false);
    }
  }

  async function handleToggle(reason: CsatReason) {
    setSavingId(reason.id);
    try {
      const { data: updated } = await api.patch<CsatReason>(
        `/widget/csat-reasons/${reason.id}`, { enabled: !reason.enabled }
      );
      setData((prev) => (prev ?? []).map((r) => (r.id === reason.id ? updated : r)));
      toast({ type: "success", message: `Motivo ${updated.enabled ? "activado" : "desactivado"}.`, duration: 1500 });
    } catch (err) {
      toast({ type: "error", title: "No se pudo actualizar el motivo", message: getErrorMessage(err) });
    } finally {
      setSavingId(null);
    }
  }

  function startEdit(reason: CsatReason) {
    setEditingId(reason.id);
    setEditingLabel(reason.label);
  }

  async function saveEdit(reason: CsatReason) {
    const label = editingLabel.trim();
    setEditingId(null);
    if (!label || label === reason.label) return;
    setSavingId(reason.id);
    try {
      const { data: updated } = await api.patch<CsatReason>(
        `/widget/csat-reasons/${reason.id}`, { label }
      );
      setData((prev) => (prev ?? []).map((r) => (r.id === reason.id ? updated : r)));
      toast({ type: "success", message: "Motivo actualizado.", duration: 1500 });
    } catch (err) {
      toast({ type: "error", title: "No se pudo actualizar el motivo", message: getErrorMessage(err) });
    } finally {
      setSavingId(null);
    }
  }

  async function handleDelete(reason: CsatReason) {
    const ok = await confirm({
      title: "Eliminar motivo",
      message: `¿Eliminar el motivo "${reason.label}"? Esta acción no se puede deshacer.`,
      confirmText: "Eliminar",
      variant: "danger",
    });
    if (!ok) return;
    setSavingId(reason.id);
    try {
      await api.delete(`/widget/csat-reasons/${reason.id}`);
      setData((prev) => (prev ?? []).filter((r) => r.id !== reason.id));
      toast({ type: "success", message: "Motivo eliminado." });
    } catch (err) {
      toast({ type: "error", title: "No se pudo eliminar el motivo", message: getErrorMessage(err) });
    } finally {
      setSavingId(null);
    }
  }

  async function persistOrder(ordered: CsatReason[]) {
    try {
      await api.put<CsatReason[]>("/widget/csat-reasons/reorder", {
        ordered_ids: ordered.map((r) => r.id),
      });
    } catch (err) {
      toast({ type: "error", title: "No se pudo guardar el orden", message: getErrorMessage(err) });
    }
  }

  function handleDrop(targetId: string) {
    if (!draggedId || draggedId === targetId || !data) {
      setDraggedId(null);
      return;
    }
    const items = [...data];
    const fromIdx = items.findIndex((r) => r.id === draggedId);
    const toIdx = items.findIndex((r) => r.id === targetId);
    if (fromIdx === -1 || toIdx === -1) {
      setDraggedId(null);
      return;
    }
    const [moved] = items.splice(fromIdx, 1);
    items.splice(toIdx, 0, moved);
    setData(items);
    setDraggedId(null);
    void persistOrder(items);
  }

  if (loading) {
    return <Skeleton className="h-32 w-full rounded-lg" />;
  }
  if (error) {
    return <p className="text-2xs text-destructive">{error}</p>;
  }

  const reasons = data ?? [];

  return (
    <div className="space-y-2">
      <p className="text-2xs text-muted-foreground">
        Motivos que el usuario puede marcar junto a la calificación. Arrastre para reordenar.
      </p>

      <div className="space-y-1.5">
        {reasons.map((reason) => (
          <div
            key={reason.id}
            draggable
            onDragStart={() => setDraggedId(reason.id)}
            onDragOver={(e) => e.preventDefault()}
            onDrop={() => handleDrop(reason.id)}
            className={`flex items-center gap-2 rounded-lg border border-border bg-background px-2.5 py-1.5 ${
              draggedId === reason.id ? "opacity-50" : ""
            }`}
          >
            <GripVertical className="w-3.5 h-3.5 text-muted-foreground/50 shrink-0 cursor-grab" />

            {editingId === reason.id ? (
              <Input
                autoFocus
                value={editingLabel}
                onChange={(e) => setEditingLabel(e.target.value)}
                onBlur={() => saveEdit(reason)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") saveEdit(reason);
                  if (e.key === "Escape") setEditingId(null);
                }}
                maxLength={120}
                className="h-7 text-xs flex-1"
              />
            ) : (
              <button
                type="button"
                onClick={() => startEdit(reason)}
                className={`flex-1 text-left text-xs truncate ${reason.enabled ? "" : "text-muted-foreground line-through"}`}
                title="Clic para editar"
              >
                {reason.label}
              </button>
            )}

            {savingId === reason.id ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin text-muted-foreground shrink-0" />
            ) : (
              <Switch checked={reason.enabled} onCheckedChange={() => handleToggle(reason)} className="shrink-0" />
            )}

            <button
              type="button"
              onClick={() => handleDelete(reason)}
              className="text-muted-foreground hover:text-destructive transition-colors shrink-0"
              title="Eliminar motivo"
            >
              <Trash2 className="w-3.5 h-3.5" />
            </button>
          </div>
        ))}

        {reasons.length === 0 && (
          <p className="text-2xs text-muted-foreground italic px-1">Sin motivos configurados.</p>
        )}
      </div>

      <div className="flex items-center gap-2 pt-1">
        <Input
          value={newLabel}
          onChange={(e) => setNewLabel(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && handleCreate()}
          placeholder="Nuevo motivo…"
          maxLength={120}
          className="h-7 text-xs flex-1"
        />
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={!newLabel.trim() || creating}
          onClick={handleCreate}
        >
          {creating ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Plus className="w-3.5 h-3.5" />}
        </Button>
      </div>
    </div>
  );
}
