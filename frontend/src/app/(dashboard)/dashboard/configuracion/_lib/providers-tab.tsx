"use client";

import { useEffect, useState } from "react";
import {
 Loader2, Save, Plus, Pencil, Trash2, Eye, EyeOff,
 Minus, Zap, AlertCircle, CheckCircle2, X, ExternalLink, RefreshCw,
 ArrowUp, ArrowDown, MoreHorizontal,
} from "lucide-react";
import api from "@/lib/api";
import {
 DropdownMenu, DropdownMenuContent, DropdownMenuItem,
 DropdownMenuSeparator, DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import type { LLMProvider } from "@/types";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Modal } from "@/components/composed/modal";
import { Input } from "@/components/ui/input";
import { Select, SelectOption } from "@/components/ui/select";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Skeleton } from "@/components/ui/skeleton";

const SUGGESTED_PROVIDERS = [
 { value: "openai", label: "OpenAI" }, { value: "anthropic", label: "Anthropic" },
 { value: "openrouter", label: "OpenRouter" }, { value: "groq", label: "Groq" },
 { value: "gemini", label: "Google Gemini" }, { value: "deepseek", label: "DeepSeek" },
 { value: "azure", label: "Azure OpenAI" }, { value: "bedrock", label: "AWS Bedrock" },
 { value: "cohere", label: "Cohere" }, { value: "mistral", label: "Mistral AI" },
 { value: "together", label: "Together AI" },
 { value: "ollama", label: "Ollama (local)" },
 { value: "lmstudio", label: "LM Studio (local)" },
 { value: "custom", label: "Otro / Custom" },
];

const MODEL_HINTS: Record<string, string> = {
 openai: "gpt-4o", anthropic: "claude-sonnet-4-6",
 openrouter: "meta-llama/llama-3.1-8b-instruct:free", groq: "llama-3.1-8b-instant",
 gemini: "gemini-2.0-flash", deepseek: "deepseek-chat",
 azure: "nombre-del-deployment",
 ollama: "llama3.2 / gpt-oss:20b-cloud / …", lmstudio: "nombre-del-modelo-cargado",
};

const PROVIDER_BASE_URLS: Record<string, string> = {
 ollama: "",
 lmstudio: "",
};

const LOCAL_PROVIDERS = new Set(["ollama", "lmstudio"]);

interface ProviderForm {
 name: string; provider_type: string; custom_type: string;
 model_name: string; api_key: string; api_base: string;
 dashboard_url: string; is_active: boolean; priority: string;
}
const emptyForm = (): ProviderForm => ({
 name: "", provider_type: "openai", custom_type: "", model_name: "",
 api_key: "", api_base: "", dashboard_url: "", is_active: true, priority: "",
});
type TestState = "idle" | "testing" | "ok" | "fail";

function ProviderPanel({ editing, onClose, onSaved }: {
 editing: LLMProvider | null; onClose: () => void; onSaved: () => void;
}) {
 const { toast } = useToast();
 const [form, setForm] = useState<ProviderForm>(emptyForm);
 const [saving, setSaving] = useState(false);
 const [showKey, setShowKey] = useState(false);
 const [testState, setTestState] = useState<TestState>("idle");
 const [testMsg, setTestMsg] = useState("");
 const [testMs, setTestMs] = useState<number | null>(null);
 const [fetchedModels, setFetchedModels] = useState<{ id: string; name: string }[] | null>(null);
 const [fetchingModels, setFetchingModels] = useState(false);
 const [fetchModelsError, setFetchModelsError] = useState<string | null>(null);

 useEffect(() => {
  if (editing) {
   const isKnown = SUGGESTED_PROVIDERS.some((p) => p.value === editing.provider_type && p.value !== "custom");
   setForm({ name: editing.name, provider_type: isKnown ? editing.provider_type : "custom",
    custom_type: isKnown ? "" : editing.provider_type, model_name: editing.model_name,
    api_key: "", api_base: editing.api_base ?? "", dashboard_url: editing.dashboard_url ?? "",
    is_active: editing.is_active,
    priority: editing.priority !== null ? String(editing.priority) : "" });
  } else { setForm(emptyForm()); }
  setTestState("idle"); setTestMsg("");
  setFetchedModels(null); setFetchModelsError(null);
 }, [editing]);

 const set = (k: keyof ProviderForm, v: unknown) => { setForm((f) => ({ ...f, [k]: v })); setTestState("idle"); };

 function handleProviderTypeChange(newType: string) {
  setForm((f) => ({
   ...f,
   provider_type: newType,
   api_base: PROVIDER_BASE_URLS[newType] ?? (["azure", "custom"].includes(newType) ? f.api_base : ""),
  }));
  setTestState("idle");
  setFetchedModels(null);
  setFetchModelsError(null);
 }

 const resolvedType = form.provider_type === "custom" ? form.custom_type : form.provider_type;
 const isLocal = LOCAL_PROVIDERS.has(form.provider_type);
 const showBaseUrl = ["azure", "custom"].includes(form.provider_type) || isLocal;

 async function handleFetchModels() {
  if (!resolvedType) return;
  setFetchingModels(true);
  setFetchModelsError(null);
  try {
   let data: { models: { id: string; name: string }[] };
   if (editing && !form.api_key) {
    // Usar la key almacenada del proveedor guardado
    ({ data } = await api.get(`/providers/${editing.id}/models`));
   } else {
    const payload: Record<string, unknown> = { provider_type: resolvedType };
    if (form.api_key) payload.api_key = form.api_key;
    if (form.api_base) payload.api_base = form.api_base;
    ({ data } = await api.post("/providers/models", payload));
   }
   setFetchedModels(data.models);
    toast({ type: "success", message: `${data.models.length} modelos cargados.`, duration: 2000 });
   } catch (err: unknown) {
    setFetchModelsError(getErrorMessage(err, "No se pudo obtener la lista de modelos"));
   } finally {
   setFetchingModels(false);
  }
 }

 async function handleTest() {
  if (!resolvedType || !form.model_name) return;
  setTestState("testing"); setTestMsg("");
  try {
   if (editing && !form.api_key) {
    const { data } = await api.post(`/providers/${editing.id}/test`);
    setTestState(data.success ? "ok" : "fail");
    if (data.success) setTestMs(data.latency_ms); else setTestMsg(data.error ?? "Error");
   } else {
    const payload: Record<string, unknown> = { provider_type: resolvedType, model_name: form.model_name };
    if (form.api_key) payload.api_key = form.api_key;
    if (form.api_base) payload.api_base = form.api_base;
    const { data } = await api.post("/providers/test", payload);
    setTestState(data.success ? "ok" : "fail");
    if (data.success) setTestMs(data.latency_ms); else setTestMsg(data.error ?? "Error");
   }
  } catch { setTestState("fail"); setTestMsg("Error al contactar el servidor"); }
 }

 async function handleSave() {
  if (!form.name.trim() || !form.model_name.trim() || !resolvedType.trim()) {
   toast({ type: "warning", title: "Campos requeridos", message: "Nombre, proveedor y modelo son obligatorios." });
   return;
  }
  setSaving(true);
  try {
   const payload: Record<string, unknown> = {
    name: form.name, provider_type: resolvedType, model_name: form.model_name,
    api_base: form.api_base || null, dashboard_url: form.dashboard_url || null,
    is_active: form.is_active,
    priority: form.priority !== "" ? Number(form.priority) : null,
   };
   if (form.api_key) payload.api_key = form.api_key;
   if (editing) { await api.patch(`/providers/${editing.id}`, payload); }
   else { await api.post("/providers", payload); }
   onSaved(); onClose();
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar.") });
  } finally { setSaving(false); }
 }

 return (
  <div className="space-y-4">
   <div>
    <label className="block text-xs font-medium text-muted-foreground mb-1">Nombre para mostrar</label>
    <Input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="ej. GPT-4o Producción" />
   </div>
   <div>
    <label className="block text-xs font-medium text-muted-foreground mb-1">Proveedor</label>
    <Select value={form.provider_type} onChange={(e) => handleProviderTypeChange(e.target.value)}>
     {SUGGESTED_PROVIDERS.map((p) => <SelectOption key={p.value} value={p.value}>{p.label}</SelectOption>)}
    </Select>
    {form.provider_type === "custom" && (
     <Input value={form.custom_type} onChange={(e) => set("custom_type", e.target.value)}
      placeholder="ej: together_ai, replicate..."
      className="mt-2" />
    )}
   </div>
   <div>
    <div className="flex items-center justify-between mb-1">
     <label className="text-xs font-medium text-muted-foreground">Modelo</label>
     {!isLocal && (
      <Button
       variant="ghost"
       size="xs"
       onClick={handleFetchModels}
       disabled={fetchingModels || !resolvedType || (!form.api_key && !editing?.has_api_key)}
       title={!form.api_key && !editing?.has_api_key ? "Ingrese una API key para obtener modelos reales" : "Obtener modelos reales del proveedor"}
       className="text-muted-foreground hover:text-primary"
      >
       {fetchingModels
        ? <Loader2 className="animate-spin" />
        : <RefreshCw />}
       {fetchedModels ? "Actualizar lista" : "Cargar modelos"}
      </Button>
     )}
    </div>
    {fetchModelsError && (
     <p className="text-2xs text-destructive mb-1 flex items-center gap-1">
      <AlertCircle className="w-3 h-3 flex-shrink-0" />{fetchModelsError}
     </p>
    )}
    {fetchedModels ? (
     <>
      <Select
       value={fetchedModels.some((m) => m.id === form.model_name) ? form.model_name : "__custom__"}
       onChange={(e) => set("model_name", e.target.value === "__custom__" ? "" : e.target.value)}
      >
       {fetchedModels.map((m) => (
        <SelectOption key={m.id} value={m.id}>{m.name}</SelectOption>
       ))}
       <SelectOption value="__custom__">Personalizado…</SelectOption>
      </Select>
      {!fetchedModels.some((m) => m.id === form.model_name) && (
       <Input value={form.model_name} onChange={(e) => set("model_name", e.target.value)}
        placeholder={MODEL_HINTS[resolvedType] ?? "nombre-del-modelo"} className="mt-2" />
      )}
      <p className="text-3xs text-muted-foreground mt-1">{fetchedModels.length} modelos obtenidos del proveedor</p>
     </>
    ) : (
     <Input value={form.model_name} onChange={(e) => set("model_name", e.target.value)}
      placeholder={MODEL_HINTS[resolvedType] ?? MODEL_HINTS[form.provider_type] ?? "nombre-del-modelo"} />
    )}
   </div>
   {!isLocal && (
    <div>
     <label className="block text-xs font-medium text-muted-foreground mb-1">
      API Key {editing?.has_api_key && <span className="text-muted-foreground">(vacío = mantener actual)</span>}
     </label>
     <div className="relative">
      <Input type={showKey ? "text" : "password"} value={form.api_key}
       onChange={(e) => set("api_key", e.target.value)}
       placeholder={editing?.has_api_key ? "••••••••••••••••" : "sk-..."}
       className="pr-10" />
      <button type="button" onClick={() => setShowKey((s) => !s)} className="absolute right-3 top-2.5 text-muted-foreground hover:text-foreground rounded focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50" aria-label={showKey ? "Ocultar API key" : "Mostrar API key"}>
       {showKey ? <EyeOff className="w-4 h-4" aria-hidden="true" /> : <Eye className="w-4 h-4" aria-hidden="true" />}
      </button>
     </div>
    </div>
   )}
   {showBaseUrl && (
    <div>
     <label className="block text-xs font-medium text-muted-foreground mb-1">
      URL base
      {form.provider_type === "azure" && <span className="text-muted-foreground ml-1">(endpoint de Azure OpenAI)</span>}
      {isLocal && <span className="text-muted-foreground ml-1">(endpoint local)</span>}
     </label>
     <Input value={form.api_base} onChange={(e) => set("api_base", e.target.value)}
      placeholder={
       form.provider_type === "azure" ? "https://mi-recurso.openai.azure.com"
       : form.provider_type === "ollama" ? "http://<host>:11434/v1"
       : form.provider_type === "lmstudio" ? "http://<host>:1234/v1"
       : "https://..."
      } />
     {isLocal && (
      <p className="mt-1 text-2xs text-muted-foreground">
       Asegúrate de que {form.provider_type === "ollama" ? "Ollama" : "LM Studio"} esté accesible en la URL indicada.
       {form.provider_type === "ollama" && " Escriba el nombre exacto del modelo (ej: llama3.2, gpt-oss:20b-cloud)."}
      </p>
     )}
    </div>
   )}
   <div>
    <label className="block text-xs font-medium text-muted-foreground mb-1">
     URL del dashboard del proveedor <span className="text-muted-foreground">(opcional)</span>
    </label>
    <Input
     type="url" value={form.dashboard_url} onChange={(e) => set("dashboard_url", e.target.value)}
     placeholder="https://platform.openai.com/usage"
    />
    <p className="mt-1 text-2xs text-muted-foreground">
     Si la completas, aparecerá un botón de acceso rápido en la tarjeta del proveedor.
    </p>
   </div>
   <div>
    <label className="block text-xs font-medium text-muted-foreground mb-1">Posición en la cadena <span className="text-muted-foreground">(1=principal, 2+=fallback, vacío=fuera)</span></label>
    <Input type="number" min={1} value={form.priority} onChange={(e) => set("priority", e.target.value)}
     placeholder="sin asignar" />
   </div>
   <div className="flex items-center justify-between py-1">
    <div>
     <p className="text-13 font-medium text-foreground">Activo</p>
     <p className="text-2xs text-muted-foreground mt-0.5">El proveedor recibirá peticiones en la cadena</p>
    </div>
    <Switch checked={form.is_active} onCheckedChange={(v) => set("is_active", v)} />
   </div>
   <div className="pt-1">
    <Button type="button" variant="outline" className="w-full gap-1.5" onClick={handleTest} disabled={testState === "testing" || !form.model_name}>
     {testState === "testing" ? <Loader2 className="w-4 h-4 animate-spin" /> : <Zap className="w-4 h-4" />}
     Probar
    </Button>
    {testState === "ok" && <p className="mt-1.5 flex items-center gap-1 text-xs text-success"><CheckCircle2 className="w-3.5 h-3.5" /> Conexión exitosa {testMs !== null && <span className="text-muted-foreground ml-1">({testMs} ms)</span>}</p>}
    {testState === "fail" && <p className="mt-1.5 flex items-start gap-1 text-xs text-destructive"><AlertCircle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" /><span className="break-all">{testMsg}</span></p>}
   </div>
   <div className="flex gap-3 pt-2 border-t border-border">
    <Button variant="outline" className="flex-1 gap-1.5" onClick={onClose}><X className="w-3.5 h-3.5" /> Cancelar</Button>
    <Button className="flex-1 gap-1.5" onClick={handleSave} disabled={saving}>
     {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : editing ? <Save className="w-3.5 h-3.5" /> : <Plus className="w-3.5 h-3.5" />}
     {editing ? "Guardar" : "Agregar"}
    </Button>
   </div>
  </div>
 );
}

// Modal estándar central (antes "SlideOver"). Reusa el <Modal> compuesto para
// mantener consistencia: header arriba, sin X, y el footer lo aporta el
// contenido (ProviderPanel) conservando su propio bloque de botones.


export function ProvidersTab() {
 const { toast, confirm } = useToast();
 const { data: providersData, loading, refetch: fetchProviders, setData: setProviders } =
  useApi<LLMProvider[]>("/providers");
 const providers = providersData ?? [];
 const [panelOpen, setPanelOpen] = useState(false);
 const [editing, setEditing] = useState<LLMProvider | null>(null);
 const [testingId, setTestingId] = useState<string | null>(null);
 const [deletingId, setDeletingId] = useState<string | null>(null);

 const chainCount = providers.filter((p) => p.priority !== null).length;

 async function handleDelete(p: LLMProvider) {
  if (deletingId) return;
  const ok = await confirm({ title: `¿Eliminar "${p.name}"?`, confirmText: "Eliminar", variant: "danger" });
  if (!ok) return;
  setDeletingId(p.id);
  try {
   await api.delete(`/providers/${p.id}`);
   fetchProviders();
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo eliminar el proveedor.") });
  } finally {
   setDeletingId(null);
  }
 }

 async function handleSetPriority(p: LLMProvider, priority: number | null) {
  await api.patch(`/providers/${p.id}`, { priority });
  fetchProviders();
 }

 async function handleQuickTest(p: LLMProvider) {
  setTestingId(p.id);
  try {
   const { data } = await api.post(`/providers/${p.id}/test`);
   // Actualiza estado local con el resultado persistido
   setProviders((prev) => (prev ?? []).map((x) => x.id === p.id ? {
    ...x,
    last_test_at: new Date().toISOString(),
    last_test_ok: !!data.success,
    last_test_latency_ms: data.latency_ms ?? null,
    last_test_error: data.success ? null : (data.error ?? null),
   } : x));
   if (data.success) toast({ type: "success", title: "Conexión exitosa", message: `Latencia: ${data.latency_ms} ms` });
   else toast({ type: "error", title: "Falló la conexión", message: data.error });
  } catch (err) { toast({ type: "error", message: getErrorMessage(err, "No se pudo contactar el servidor.") }); }
  finally { setTestingId(null); }
 }

 const chainProviders = providers.filter((p) => p.priority !== null).sort((a, b) => (a.priority ?? 0) - (b.priority ?? 0));
 const offChainProviders = providers.filter((p) => p.priority === null);

 async function persistReorder(reordered: LLMProvider[]) {
  // Optimistic
  setProviders((prev) => {
   const map = new Map(reordered.map((p, i) => [p.id, i + 1]));
   return (prev ?? []).map((p) => map.has(p.id) ? { ...p, priority: map.get(p.id)! } : p);
  });
  try {
   const items = [
    ...reordered.map((p, i) => ({ id: p.id, priority: i + 1 })),
    ...offChainProviders.map((p) => ({ id: p.id, priority: null })),
   ];
   await api.post("/providers/reorder", { items });
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo reordenar la cadena.") });
   fetchProviders();
  }
 }
 async function moveInChain(idx: number, direction: -1 | 1) {
  const targetIdx = idx + direction;
  if (targetIdx < 0 || targetIdx >= chainProviders.length) return;
  const reordered = [...chainProviders];
  [reordered[idx], reordered[targetIdx]] = [reordered[targetIdx], reordered[idx]];
  await persistReorder(reordered);
 }

 return (
  <div>
   <Card className="overflow-hidden">
    <div className="flex flex-col gap-3 px-5 py-4 border-b border-border/60">
     <div className="min-w-0">
      <p className="text-sm font-semibold text-foreground">Cadena de proveedores</p>
      <p className="text-2xs text-muted-foreground mt-0.5">Proveedor 1 = principal · 2+ = fallback automático</p>
     </div>
     <div className="grid grid-cols-1 sm:flex sm:justify-end gap-2">
      <Button size="sm" className="gap-1.5" onClick={() => { setEditing(null); setPanelOpen(true); }}>
       <Plus className="w-3.5 h-3.5" /> Agregar
      </Button>
     </div>
    </div>
    {loading ? (
     <div className="p-5 space-y-3">
      <div className="flex items-center gap-3">
       <Skeleton className="h-4 w-16" />
       <Skeleton className="h-4 w-40" />
       <Skeleton className="h-4 w-32 hidden md:block" />
       <Skeleton className="h-4 w-24 hidden sm:block" />
       <Skeleton className="h-4 w-28 hidden lg:block" />
       <Skeleton className="h-4 w-14 ml-auto" />
      </div>
      {[1,2,3].map((i) => (
       <div key={i} className="flex items-center gap-3 border-t border-border pt-3">
        <Skeleton className="h-6 w-6 rounded-full" />
        <Skeleton className="h-4 w-40" />
        <Skeleton className="h-4 w-32 hidden md:block" />
        <Skeleton className="h-4 w-20 hidden sm:block" />
        <Skeleton className="h-4 w-24 hidden lg:block" />
        <Skeleton className="h-4 w-14 ml-auto" />
       </div>
      ))}
     </div>
    ) : providers.length === 0 ? (
     <div className="text-center py-16">
      <p className="text-sm text-muted-foreground">No hay proveedores configurados.</p>
      <Button variant="link" size="sm" onClick={() => { setEditing(null); setPanelOpen(true); }} className="mt-3">+ Agregar el primero</Button>
     </div>
    ) : (
     <div className="overflow-x-auto">
     <Table>
      <TableHeader>
       <TableRow>
        <TableHead className="w-16">Orden</TableHead>
        <TableHead>Proveedor</TableHead>
        <TableHead className="hidden md:table-cell">Modelo</TableHead>
        <TableHead className="w-28 hidden sm:table-cell">Estado</TableHead>
        <TableHead className="w-32 hidden lg:table-cell">Salud</TableHead>
         <TableHead className="w-14 text-right" sticky>Acciones</TableHead>
       </TableRow>
      </TableHeader>
      <TableBody>
       {chainProviders.map((p, idx) => (
        <ProviderRow
         key={p.id}
         p={p}
         inChain
         idx={idx}
         onMoveUp={idx > 0 ? () => moveInChain(idx, -1) : undefined}
         onMoveDown={idx < chainProviders.length - 1 ? () => moveInChain(idx, 1) : undefined}
          testingId={testingId}
          handleQuickTest={handleQuickTest}
          handleSetPriority={handleSetPriority}
          handleDelete={handleDelete}
          deletingId={deletingId}
         setEditing={setEditing}
         setPanelOpen={setPanelOpen}
         chainCount={chainCount}
        />
       ))}
       {offChainProviders.map((p) => (
        <ProviderRow
         key={p.id}
         p={p}
          inChain={false}
          idx={-1}
          testingId={testingId}
          handleQuickTest={handleQuickTest}
          handleSetPriority={handleSetPriority}
         handleDelete={handleDelete}
         deletingId={deletingId}
         setEditing={setEditing}
         setPanelOpen={setPanelOpen}
         chainCount={chainCount}
        />
       ))}
      </TableBody>
      </Table>
      </div>
     )}
    </Card>
   <Modal open={panelOpen} title={editing ? "Editar proveedor" : "Agregar proveedor"} onClose={() => setPanelOpen(false)}>
    <ProviderPanel editing={editing} onClose={() => setPanelOpen(false)} onSaved={fetchProviders} />
   </Modal>
  </div>
 );
}

// ProviderRow — fila de tabla reutilizable para cadena y fuera-de-cadena
interface ProviderRowProps {
 p: LLMProvider;
 inChain: boolean;
 idx: number;
 onMoveUp?: () => void;
 onMoveDown?: () => void;
  testingId: string | null;
  handleQuickTest: (p: LLMProvider) => void;
 handleSetPriority: (p: LLMProvider, priority: number | null) => void;
 handleDelete: (p: LLMProvider) => void;
 deletingId: string | null;
 setEditing: (p: LLMProvider | null) => void;
 setPanelOpen: (b: boolean) => void;
 chainCount: number;
}

function ProviderRow({
 p, inChain, onMoveUp, onMoveDown,
  testingId, handleQuickTest, handleSetPriority,
 handleDelete, deletingId, setEditing, setPanelOpen, chainCount,
}: ProviderRowProps) {
 const isMain = p.priority === 1;
 const isTesting = testingId === p.id;

 // Badge de estado real
 let healthBadge: { label: string; cls: string } | null = null;
 if (p.last_test_at == null) {
  healthBadge = { label: "Sin probar", cls: "bg-muted text-muted-foreground border-border" };
 } else if (p.last_test_ok) {
  healthBadge = { label: `OK · ${p.last_test_latency_ms ?? "?"}ms`, cls: "bg-success/10 text-success border-success/30" };
 } else {
  healthBadge = { label: "Error", cls: "bg-destructive/5 text-destructive border-destructive/20" };
 }

 return (
  <TableRow className={!p.is_active ? "opacity-50" : ""}>
   <TableCell>
    {inChain ? (
     <div className="flex items-center gap-1.5">
      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-3xs font-bold shrink-0 ${isMain ? "bg-primary text-primary-foreground" : "bg-muted text-muted-foreground"}`}>
       {p.priority}
      </div>
      <div className="flex flex-col gap-0.5 shrink-0">
       <Button variant="ghost" size="icon-xs" onClick={onMoveUp} disabled={!onMoveUp} title="Mover arriba" aria-label={`Mover ${p.name} arriba en la cadena`} className="text-muted-foreground h-4 w-4"><ArrowUp aria-hidden="true" /></Button>
       <Button variant="ghost" size="icon-xs" onClick={onMoveDown} disabled={!onMoveDown} title="Mover abajo" aria-label={`Mover ${p.name} abajo en la cadena`} className="text-muted-foreground h-4 w-4"><ArrowDown aria-hidden="true" /></Button>
      </div>
     </div>
    ) : (
     <span className="text-muted-foreground">—</span>
    )}
   </TableCell>
   <TableCell className="max-w-32 sm:max-w-none">
    <p className="text-13 font-medium text-foreground truncate">{p.name}</p>
   </TableCell>
   <TableCell className="hidden md:table-cell">
    <p className="text-13 text-foreground truncate max-w-56">{p.model_name}</p>
   </TableCell>
   <TableCell className="hidden sm:table-cell">
    {p.is_active
     ? <span className="text-2xs text-success bg-success/10 px-1.5 py-0.5 rounded-full">Activo</span>
     : <span className="text-2xs text-muted-foreground bg-muted px-1.5 py-0.5 rounded-full">Inactivo</span>}
   </TableCell>
   <TableCell className="hidden lg:table-cell">
    <span className={`text-3xs px-1.5 py-0.5 rounded-full border tabular-nums whitespace-nowrap ${healthBadge.cls}`}>
     {healthBadge.label}
    </span>
   </TableCell>
   <TableCell sticky>
     <DropdownMenu>
      <DropdownMenuTrigger asChild>
       <Button variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground">
        <MoreHorizontal className="w-4 h-4" />
       </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-48">
       {!inChain ? (
        <DropdownMenuItem onClick={() => handleSetPriority(p, chainCount + 1)} className="whitespace-nowrap">
         <Plus className="w-3.5 h-3.5 mr-2" />
         Agregar a la cadena
        </DropdownMenuItem>
       ) : (
        <DropdownMenuItem onClick={() => handleSetPriority(p, null)} className="whitespace-nowrap">
         <Minus className="w-3.5 h-3.5 mr-2" />
         Quitar de la cadena
        </DropdownMenuItem>
       )}
       <DropdownMenuItem onClick={() => handleQuickTest(p)} disabled={isTesting}>
        {isTesting ? <Loader2 className="w-3.5 h-3.5 mr-2 animate-spin" /> : <Zap className="w-3.5 h-3.5 mr-2" />}
        Probar conexión
       </DropdownMenuItem>
       {p.dashboard_url && (
        <DropdownMenuItem onClick={() => window.open(p.dashboard_url!, '_blank', 'noopener,noreferrer')}>
         <ExternalLink className="w-3.5 h-3.5 mr-2" />
         Dashboard
        </DropdownMenuItem>
       )}
       <DropdownMenuSeparator />
       <DropdownMenuItem onClick={() => { setEditing(p); setPanelOpen(true); }}>
        <Pencil className="w-3.5 h-3.5 mr-2" />
        Editar
       </DropdownMenuItem>
       <DropdownMenuItem onClick={() => handleDelete(p)} disabled={!!deletingId} className="text-destructive focus:text-destructive focus:bg-destructive/10">
        <Trash2 className="w-3.5 h-3.5 mr-2" />
        Eliminar
       </DropdownMenuItem>
      </DropdownMenuContent>
     </DropdownMenu>
    </TableCell>
  </TableRow>
 );
}
