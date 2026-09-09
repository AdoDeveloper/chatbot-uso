"use client";

import { useEffect, useState, useRef, forwardRef, useImperativeHandle, useCallback } from "react";
import { Loader2, Save, Plus, Pencil, Trash2, X, AlertCircle, MoreHorizontal } from "lucide-react";
import api from "@/lib/api";
import {
 DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { getErrorMessage, invalidateApiCache } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import type { ProviderTypeCatalogItem } from "@/types";
import { Button } from "@/components/ui/button";
import { Modal } from "@/components/composed/modal";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { EmptyState } from "@/components/ui/empty-state";

interface HeaderPair { key: string; value: string }

interface CatalogForm {
 type_key: string; display_name: string; default_api_base: string;
 models_endpoint_path: string; notes: string; headers: HeaderPair[];
}
const emptyForm = (): CatalogForm => ({
 type_key: "", display_name: "", default_api_base: "",
 models_endpoint_path: "/models", notes: "", headers: [],
});

interface CatalogPanelHandle { save: () => void }

const CatalogPanel = forwardRef<CatalogPanelHandle, {
 editing: ProviderTypeCatalogItem | null;
 onClose: () => void; onSaved: () => void; onSavingChange: (saving: boolean) => void;
}>(function CatalogPanel({ editing, onClose, onSaved, onSavingChange }, ref) {
 const { toast } = useToast();
 const [form, setForm] = useState<CatalogForm>(emptyForm);

 useEffect(() => {
  if (editing) {
   setForm({
    type_key: editing.type_key, display_name: editing.display_name,
    default_api_base: editing.default_api_base ?? "",
    models_endpoint_path: editing.models_endpoint_path || "/models",
    notes: editing.notes ?? "",
    headers: Object.entries(editing.default_headers ?? {}).map(([key, value]) => ({ key, value })),
   });
  } else { setForm(emptyForm()); }
 }, [editing]);

 const set = (k: keyof CatalogForm, v: unknown) => setForm((f) => ({ ...f, [k]: v }));

 function addHeader() { setForm((f) => ({ ...f, headers: [...f.headers, { key: "", value: "" }] })); }
 function updateHeader(i: number, field: "key" | "value", v: string) {
  setForm((f) => ({ ...f, headers: f.headers.map((h, idx) => idx === i ? { ...h, [field]: v } : h) }));
 }
 function removeHeader(i: number) {
  setForm((f) => ({ ...f, headers: f.headers.filter((_, idx) => idx !== i) }));
 }

 const handleSave = useCallback(async () => {
  if (!form.type_key.trim() || !form.display_name.trim()) {
   toast({ type: "warning", title: "Campos requeridos", message: "Clave y nombre son obligatorios." });
   return;
  }
  onSavingChange(true);
  try {
   const default_headers: Record<string, string> = {};
   for (const h of form.headers) {
    if (h.key.trim()) default_headers[h.key.trim()] = h.value;
   }
   const payload = {
    type_key: form.type_key.trim(),
    display_name: form.display_name.trim(),
    default_api_base: form.default_api_base.trim() || null,
    models_endpoint_path: form.models_endpoint_path.trim() || "/models",
    notes: form.notes.trim() || null,
    default_headers,
   };
   invalidateApiCache("/provider-types");
   if (editing) { await api.patch(`/provider-types/${editing.id}`, payload); }
   else { await api.post("/provider-types", payload); }
   onSaved(); onClose();
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar.") });
  } finally { onSavingChange(false); }
 }, [form, editing, onClose, onSaved, onSavingChange, toast]);

 useImperativeHandle(ref, () => ({ save: handleSave }), [handleSave]);

 return (
  <div className="space-y-4">
   <div>
    <label className="block text-xs font-medium text-muted-foreground mb-1">Clave (type_key)</label>
    <Input value={form.type_key} onChange={(e) => set("type_key", e.target.value.trim().toLowerCase())}
     placeholder="ej. together" autoComplete="off" />
    <p className="mt-1 text-2xs text-muted-foreground">Es el valor que se guarda en cada proveedor (provider_type). No usar espacios.</p>
   </div>
   <div>
    <label className="block text-xs font-medium text-muted-foreground mb-1">Nombre para mostrar</label>
    <Input value={form.display_name} onChange={(e) => set("display_name", e.target.value)}
     placeholder="ej. Together AI" autoComplete="off" />
   </div>
   <div>
    <label className="block text-xs font-medium text-muted-foreground mb-1">
     URL base por defecto <span className="text-muted-foreground">(opcional)</span>
    </label>
    <Input value={form.default_api_base} onChange={(e) => set("default_api_base", e.target.value)}
     placeholder="https://api.ejemplo.com/v1" autoComplete="off" />
   </div>
   <div>
    <label className="block text-xs font-medium text-muted-foreground mb-1">Ruta del listado de modelos</label>
    <Input value={form.models_endpoint_path} onChange={(e) => set("models_endpoint_path", e.target.value)}
     placeholder="/models" autoComplete="off" />
    <p className="mt-1 text-2xs text-muted-foreground">La mayoría usa /models. Algunos proveedores difieren (ej. /serverless-models).</p>
   </div>
   <div>
    <div className="flex items-center justify-between mb-1">
     <label className="text-xs font-medium text-muted-foreground">Headers HTTP extra</label>
     <Button variant="ghost" size="xs" onClick={addHeader} className="text-muted-foreground hover:text-primary">
      <Plus className="w-3 h-3" /> Agregar
     </Button>
    </div>
    {form.headers.length === 0 ? (
     <p className="text-2xs text-muted-foreground">Ninguno. Algunos proveedores requieren headers propios (ej. Cloudflare: cf-aig-gateway-id).</p>
    ) : (
     <div className="space-y-2">
      {form.headers.map((h, i) => (
       <div key={i} className="flex gap-2 items-center">
        <Input value={h.key} onChange={(e) => updateHeader(i, "key", e.target.value)} placeholder="nombre-header" className="flex-1" autoComplete="off" />
        <Input value={h.value} onChange={(e) => updateHeader(i, "value", e.target.value)} placeholder="valor" className="flex-1" autoComplete="off" />
        <Button variant="ghost" size="icon-xs" onClick={() => removeHeader(i)} aria-label="Quitar header" className="text-muted-foreground hover:text-destructive shrink-0">
         <X className="w-3.5 h-3.5" />
        </Button>
       </div>
      ))}
     </div>
    )}
   </div>
   <div>
    <label className="block text-xs font-medium text-muted-foreground mb-1">
     Notas <span className="text-muted-foreground">(opcional)</span>
    </label>
    <Input value={form.notes} onChange={(e) => set("notes", e.target.value)}
     placeholder="ej. Servicio descontinuado, requiere product_id, etc." autoComplete="off" />
   </div>
  </div>
 );
});

export function ProviderTypesPanel({
 catalogTypes, onChanged,
}: { catalogTypes: ProviderTypeCatalogItem[]; onChanged: () => void }) {
 const { toast, confirm } = useToast();
 const [panelOpen, setPanelOpen] = useState(false);
 const [editing, setEditing] = useState<ProviderTypeCatalogItem | null>(null);
 const [deletingId, setDeletingId] = useState<string | null>(null);
 const [panelSaving, setPanelSaving] = useState(false);
 const panelRef = useRef<CatalogPanelHandle>(null);

 async function handleDelete(t: ProviderTypeCatalogItem) {
  if (deletingId) return;
  const ok = await confirm({ title: `¿Eliminar tipo "${t.display_name}"?`, confirmText: "Eliminar", variant: "danger" });
  if (!ok) return;
  setDeletingId(t.id);
  try {
   invalidateApiCache("/provider-types");
   await api.delete(`/provider-types/${t.id}`);
   onChanged();
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo eliminar el tipo de proveedor.") });
  } finally { setDeletingId(null); }
 }

 return (
  <Card className="overflow-hidden">
   <div className="flex flex-col gap-3 px-5 py-4 border-b border-border/60">
    <div className="min-w-0">
     <p className="text-sm font-semibold text-foreground">Tipos de proveedor</p>
     <p className="text-2xs text-muted-foreground mt-0.5">Catálogo editable de URL base y headers por defecto para cada tipo de proveedor.</p>
    </div>
    <div className="grid grid-cols-1 sm:flex sm:justify-end gap-2">
     <Button size="sm" variant="outline" className="gap-1.5" onClick={() => { setEditing(null); setPanelOpen(true); }}>
      <Plus className="w-3.5 h-3.5" /> Agregar tipo
     </Button>
    </div>
   </div>
   {catalogTypes.length === 0 ? (
    <EmptyState
     icon={AlertCircle}
     title="Sin tipos de proveedor"
     description="Agregue un tipo de proveedor para poblar el selector al crear proveedores LLM."
    />
   ) : (
    <div className="overflow-x-auto">
     <Table>
      <TableHeader>
       <TableRow>
        <TableHead>Clave</TableHead>
        <TableHead>Nombre</TableHead>
        <TableHead className="hidden md:table-cell">URL base</TableHead>
        <TableHead className="hidden lg:table-cell">Notas</TableHead>
        <TableHead className="whitespace-nowrap text-right" sticky>Acciones</TableHead>
       </TableRow>
      </TableHeader>
      <TableBody>
       {catalogTypes.map((t) => (
        <TableRow key={t.id}>
         <TableCell><code className="text-2xs">{t.type_key}</code></TableCell>
         <TableCell><p className="text-13 font-medium text-foreground">{t.display_name}</p></TableCell>
         <TableCell className="hidden md:table-cell">
          <p className="text-13 text-muted-foreground truncate max-w-64">{t.default_api_base ?? "—"}</p>
         </TableCell>
         <TableCell className="hidden lg:table-cell">
          {t.notes ? (
           <span className="text-2xs text-warning flex items-center gap-1 max-w-64">
            <AlertCircle className="w-3 h-3 flex-shrink-0" />
            <span className="truncate">{t.notes}</span>
           </span>
          ) : <span className="text-muted-foreground">—</span>}
         </TableCell>
         <TableCell sticky className="whitespace-nowrap">
          <DropdownMenu>
           <DropdownMenuTrigger asChild>
            <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground">
             <MoreHorizontal className="w-4 h-4" />
            </Button>
           </DropdownMenuTrigger>
           <DropdownMenuContent align="end" className="w-40">
            <DropdownMenuItem onClick={() => { setEditing(t); setPanelOpen(true); }}>
             <Pencil className="w-3.5 h-3.5 mr-2" /> Editar
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => handleDelete(t)} disabled={!!deletingId} className="text-destructive focus:text-destructive focus:bg-destructive/10">
             <Trash2 className="w-3.5 h-3.5 mr-2" /> Eliminar
            </DropdownMenuItem>
           </DropdownMenuContent>
          </DropdownMenu>
         </TableCell>
        </TableRow>
       ))}
      </TableBody>
     </Table>
    </div>
   )}
   <Modal
    open={panelOpen}
    title={editing ? "Editar tipo de proveedor" : "Agregar tipo de proveedor"}
    onClose={() => setPanelOpen(false)}
    footer={
     <>
      <Button variant="outline" className="flex-1 gap-1.5" onClick={() => setPanelOpen(false)}><X className="w-3.5 h-3.5" /> Cancelar</Button>
      <Button className="flex-1 gap-1.5" onClick={() => panelRef.current?.save()} disabled={panelSaving}>
       {panelSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : editing ? <Save className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
       {editing ? "Guardar" : "Agregar"}
      </Button>
     </>
    }
   >
    <CatalogPanel ref={panelRef} editing={editing} onClose={() => setPanelOpen(false)} onSaved={onChanged} onSavingChange={setPanelSaving} />
   </Modal>
  </Card>
 );
}
