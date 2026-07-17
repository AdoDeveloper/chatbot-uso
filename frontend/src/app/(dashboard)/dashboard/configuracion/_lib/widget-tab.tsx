"use client";

import { useEffect, useState } from "react";
import {
 Loader2, Save, Copy, Check, Plus, X, ChevronRight, Eye,
} from "lucide-react";

import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import type { WidgetConfig } from "@/types";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Input } from "@/components/ui/input";
import { SegmentedControl } from "@/components/composed/segmented-control";
import { FloatingSaveBar } from "./save-bar";
import { Loading } from "@/components/ui/loading";

// Lightweight inline disclosure — used inside a card to hide secondary toggles
// behind a "Más opciones" link. Doesn't render its own card chrome.
function InlineDisclosure({ label, children }: { label: string; children: React.ReactNode }) {
 const [open, setOpen] = useState(false);
 return (
  <div>
   <button
    type="button"
    onClick={() => setOpen((o) => !o)}
    className="flex items-center gap-1 mt-2 py-1 text-xs font-medium text-muted-foreground hover:text-foreground transition-colors"
   >
    <ChevronRight className={`w-3 h-3 transition-transform ${open ? "rotate-90" : ""}`} />
    {label}
   </button>
   {open && <div className="space-y-0">{children}</div>}
  </div>
 );
}

function SettingToggle({ label, description, checked, onChange }: {
 label: string; description?: string; checked: boolean; onChange: (v: boolean) => void;
}) {
 return (
  <div className="flex items-center justify-between py-3">
   <div>
    <p className="text-13 font-medium text-foreground">{label}</p>
    {description && <p className="text-2xs text-muted-foreground mt-0.5">{description}</p>}
   </div>
   <Switch checked={checked} onCheckedChange={onChange} />
  </div>
 );
}

function WidgetApiKey({ config, onRegenerated }: {
 config: WidgetConfig | null;
 onRegenerated: (c: WidgetConfig) => void;
}) {
 const { toast, confirm } = useToast();
 const [copying, setCopying] = useState(false);
 const [regenerating, setRegenerating] = useState(false);

 if (!config?.api_key) return null;

 async function handleCopy() {
  await navigator.clipboard.writeText(config!.api_key);
  setCopying(true);
  setTimeout(() => setCopying(false), 2000);
 }

 async function handleRegenerate() {
  const ok = await confirm({
   title: "¿Regenerar clave del widget?",
   message: "Todos los widgets existentes dejarán de funcionar hasta que actualices el código de integración.",
   confirmText: "Regenerar", variant: "danger",
  });
  if (!ok) return;
  setRegenerating(true);
  try {
   const { data } = await api.post<WidgetConfig>("/widget/regenerate-key");
   onRegenerated(data);
   toast({ type: "success", message: "Clave regenerada correctamente." });
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo regenerar la clave.") });
  } finally { setRegenerating(false); }
 }

 return (
  <div className="bg-card border border-border rounded-xl shadow-sm p-6">
   <h3 className="text-15 font-semibold tracking-tight mb-1">Clave API del widget</h3>
   <p className="text-13 text-muted-foreground mb-4">
    Esta clave identifica su widget y se incluye automáticamente en el código de integración.
   </p>
   <div className="flex gap-2">
    <Input
     readOnly
     value={config.api_key}
     className="flex-1 font-mono select-all"
     onClick={(e) => (e.target as HTMLInputElement).select()}
    />
    <Button variant="outline" size="sm" className="h-9 px-3" onClick={handleCopy}>
     {copying ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
    </Button>
    <Button variant="destructive" size="sm" className="h-9 px-3 text-13" onClick={handleRegenerate} disabled={regenerating}>
     {regenerating ? "Regenerando..." : "Regenerar"}
    </Button>
   </div>
  </div>
 );
}

function DomainAllowlist({
 config, setConfig,
}: {
 config: WidgetConfig | null;
 setConfig: React.Dispatch<React.SetStateAction<WidgetConfig | null>>;
}) {
 const [newDomain, setNewDomain] = useState("");

 if (!config) return null;
 const domains = config.domain_allowlist ?? [];

 function addDomain() {
  const d = newDomain.trim().toLowerCase();
  if (!d || domains.includes(d)) return;
  setConfig((c) => c ? { ...c, domain_allowlist: [...(c.domain_allowlist ?? []), d] } : c);
  setNewDomain("");
 }

 function removeDomain(domain: string) {
  setConfig((c) => c ? { ...c, domain_allowlist: (c.domain_allowlist ?? []).filter((x) => x !== domain) } : c);
 }

 // Sin botón "Guardar" propio: los dominios editan el mismo estado que el
 // resto del tab y se persisten con la barra flotante global — antes había
 // dos botones de guardado con alcances distintos en la misma pantalla.
 return (
  <div className="bg-card border border-border rounded-xl shadow-sm p-6">
   <div className="flex items-center justify-between mb-1">
    <h3 className="text-15 font-semibold tracking-tight">Dominios permitidos</h3>
   </div>
   <p className="text-13 text-muted-foreground mb-4">
    Sitios web que pueden cargar el widget. Usa <code className="text-xs bg-muted px-1 rounded">*.ejemplo.com</code> para incluir subdominios. Si la lista está vacía, cualquier sitio puede usarlo.
   </p>
   <div className="flex gap-2 mb-3">
    <Input
     value={newDomain}
     onChange={(e) => setNewDomain(e.target.value)}
     onKeyDown={(e) => e.key === "Enter" && addDomain()}
     placeholder="ejemplo.com o *.ejemplo.com"
     className="flex-1"
    />
    <Button size="sm" className="h-8 px-3" onClick={addDomain}>
     <Plus className="w-3.5 h-3.5" />
    </Button>
   </div>
   {domains.length > 0 ? (
    <div className="space-y-1.5">
     {domains.map((d) => (
      <div key={d} className="flex items-center justify-between px-3 py-2 border border-border rounded-md">
       <span className="text-sm font-mono text-foreground">{d}</span>
       <Button variant="ghost" size="icon" onClick={() => removeDomain(d)} aria-label={`Quitar dominio ${d}`} className="h-7 w-7 text-muted-foreground hover:text-destructive">
        <X className="w-3.5 h-3.5" aria-hidden="true" />
       </Button>
      </div>
     ))}
    </div>
   ) : (
    <p className="text-2xs text-muted-foreground italic">Sin restricciones — el widget se puede incrustar en cualquier dominio.</p>
   )}
  </div>
 );
}

// Selector visual de la esquina donde vive el widget. Grilla 2x2 con flechas
// SVG apuntando hacia cada esquina. Sin emojis (regla del proyecto: solo SVG).
type WidgetPosition = "bottom-right" | "bottom-left" | "top-right" | "top-left";

function PositionPicker({ value, onChange }: { value: string; onChange: (p: WidgetPosition) => void }) {
 // Cada celda tiene su esquina target + el rotation del icono de flecha. La
 // flecha base apunta hacia abajo-derecha (45°), las demás se rotan.
 const POSITIONS: { id: WidgetPosition; label: string; rotate: number }[] = [
  { id: "top-left",     label: "Superior izquierda", rotate: 225 },
  { id: "top-right",    label: "Superior derecha",   rotate: 315 },
  { id: "bottom-left",  label: "Inferior izquierda", rotate: 135 },
  { id: "bottom-right", label: "Inferior derecha",   rotate: 45 },
 ];
 return (
  <div className="grid grid-cols-2 gap-2 w-44">
   {POSITIONS.map((p) => {
    const active = value === p.id;
    return (
     <button
      key={p.id}
      type="button"
      onClick={() => onChange(p.id)}
      title={p.label}
      aria-label={p.label}
      aria-pressed={active}
      className={`flex items-center justify-center h-12 rounded-md border transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring/50 ${
       active
        ? "border-primary bg-primary/10 text-primary"
        : "border-border bg-background text-muted-foreground hover:border-border/80 hover:bg-muted/50"
      }`}
     >
      <svg
       viewBox="0 0 24 24"
       fill="none"
       stroke="currentColor"
       strokeWidth={2.2}
       strokeLinecap="round"
       strokeLinejoin="round"
       width={20}
       height={20}
       style={{ transform: `rotate(${p.rotate}deg)` }}
       aria-hidden="true"
      >
       <line x1="5" y1="12" x2="19" y2="12" />
       <polyline points="12 5 19 12 12 19" />
      </svg>
     </button>
    );
   })}
  </div>
 );
}


// Límites en sync con backend (schemas/widget.py). Si cambian allá, actualizar
// aquí también — el backend valida igual, así que TS solo es para UX.
const MAX_PROACTIVE_LEN = 200;
const MAX_SUGGESTIONS = 6;
const MAX_SUGGESTION_LEN = 60;

// Input para el mensaje proactivo con counter visible y mini-preview.
function ProactiveMessageInput({ value, onChange }: { value: string; onChange: (v: string) => void }) {
 const remaining = MAX_PROACTIVE_LEN - value.length;
 const overLimit = remaining < 0;
 return (
  <div className="space-y-2">
   <div className="relative">
    <Input
     type="text"
     value={value}
     onChange={(e) => onChange(e.target.value)}
     placeholder='Ej: "¿Tenés dudas sobre la universidad? Preguntame."'
     maxLength={MAX_PROACTIVE_LEN + 20}  // tope con margen, validacion real abajo
     className={`pr-14 ${overLimit ? "border-destructive" : ""}`}
    />
    <span className={`absolute right-2 top-1/2 -translate-y-1/2 text-3xs tabular-nums ${
     overLimit ? "text-destructive" : remaining < 30 ? "text-amber-600" : "text-muted-foreground"
    }`}>
     {value.length}/{MAX_PROACTIVE_LEN}
    </span>
   </div>
   {value && (
    <div className="text-2xs text-muted-foreground">
     Vista previa:{" "}
     <span className="inline-block bg-card border border-border rounded-lg rounded-br-sm px-2.5 py-1 text-foreground max-w-full break-words">
      {value}
     </span>
    </div>
   )}
  </div>
 );
}

function SuggestionsEditor({ value, onChange }: { value: string[]; onChange: (v: string[]) => void }) {
 const atMax = value.length >= MAX_SUGGESTIONS;
 const update = (i: number, v: string) => {
  const next = [...value];
  next[i] = v;
  onChange(next);
 };
 const remove = (i: number) => onChange(value.filter((_, idx) => idx !== i));
 const add = () => { if (!atMax) onChange([...value, ""]); };

 return (
  <div className="space-y-2">
   {value.length === 0 ? (
    <p className="text-2xs text-muted-foreground italic py-1">
     Sin sugerencias. Agregá una para que aparezca como botón en el chat.
    </p>
   ) : (
    value.map((s, i) => (
     <div key={i} className="flex items-center gap-2">
      <Input
       type="text"
       value={s}
       onChange={(e) => update(i, e.target.value)}
       placeholder={`Sugerencia ${i + 1}`}
       maxLength={MAX_SUGGESTION_LEN}
       className="flex-1"
      />
      <Button
       type="button"
       variant="ghost"
       size="icon"
       onClick={() => remove(i)}
       aria-label={`Quitar sugerencia ${i + 1}`}
       className="w-7 h-7 text-muted-foreground hover:text-destructive hover:bg-destructive/10"
      >
       <svg viewBox="0 0 24 24" width={14} height={14} fill="none" stroke="currentColor" strokeWidth={2} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <line x1="18" y1="6" x2="6" y2="18" />
        <line x1="6" y1="6" x2="18" y2="18" />
       </svg>
      </Button>
     </div>
    ))
   )}
   <div className="flex items-center justify-between">
    <Button
     type="button"
     variant="outline"
     size="sm"
     onClick={add}
     disabled={atMax}
     className="gap-1.5 h-7"
    >
     <svg viewBox="0 0 24 24" width={12} height={12} fill="none" stroke="currentColor" strokeWidth={2.5} strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <line x1="12" y1="5" x2="12" y2="19" />
      <line x1="5" y1="12" x2="19" y2="12" />
     </svg>
     Agregar
    </Button>
    <span className="text-3xs text-muted-foreground tabular-nums">
     {value.length} / {MAX_SUGGESTIONS}
    </span>
   </div>
  </div>
 );
}

export type WidgetSubtab = "apariencia" | "integracion" | "limites";

interface WidgetTabProps {
 subtab: WidgetSubtab;
 onPreview: () => void;
 /**
  * Estado del config elevado al padre (página Asistente) para que el
  * formulario de Apariencia y el preview funcional compartan el MISMO objeto
  * y los cambios se reflejen en vivo. Si no se pasan, el componente maneja su
  * propio estado (uso standalone).
  */
 config?: WidgetConfig | null;
 setConfig?: React.Dispatch<React.SetStateAction<WidgetConfig | null>>;
}

/**
 * Contenido de las secciones Apariencia/Integración/Límites del chatbot.
 * La navegación entre subtabs la controla el padre (página Asistente) para
 * que viva en una sola fila de tabs junto a Identidad/Prompt/Previsualizar —
 * antes esto tenía su propia barra de tabs anidada.
 */
export function WidgetTab({ subtab, onPreview, config: configProp, setConfig: setConfigProp }: WidgetTabProps) {
 const { toast } = useToast();
 const [snippetKind, setSnippetKind] = useState<"script" | "iframe">("script");
 const [configOwn, setConfigOwn] = useState<WidgetConfig | null>(null);
 const [savedConfig, setSavedConfig] = useState<WidgetConfig | null>(null);
 const [captacionOpen, setCaptacionOpen] = useState(false);
 const [saving, setSaving] = useState(false);
 const [copied, setCopied] = useState(false);

 // Si el padre provee estado, usamos ESE (fuente única compartida con el
 // preview); si no, el estado local propio.
 const config = configProp !== undefined ? configProp : configOwn;
 const setConfig = setConfigProp ?? setConfigOwn;

 const { data: widgetData, loading: loadingWidget } = useApi<WidgetConfig>("/widget/config");
 const { data: embedData, loading: loadingEmbed } =
  useApi<{ script_tag: string; iframe_tag: string }>("/widget/embed-code");
 const loading = loadingWidget || loadingEmbed;
 const scriptTag = embedData?.script_tag ?? "";
 const iframeTag = embedData?.iframe_tag ?? "";

 // Sembrar el estado editable cuando llega la config del backend.
 useEffect(() => {
  if (!widgetData) return;
  setConfig(widgetData);
  setSavedConfig(widgetData);
  // Captación abierta si algún campo tiene contenido
  setCaptacionOpen(
   (widgetData.proactive_message ?? "") !== "" ||
   (widgetData.suggestions ?? []).length > 0
  );
  // eslint-disable-next-line react-hooks/exhaustive-deps
 }, [widgetData]);

 const currentSnippet = snippetKind === "script" ? scriptTag : iframeTag;
 const isDirty = config !== null && savedConfig !== null &&
  JSON.stringify(config) !== JSON.stringify(savedConfig);

 async function handleSave() {
  if (!config) return;
  if (!config.chatbot_name?.trim()) {
   toast({ type: "error", message: "El nombre del chatbot no puede estar vacío." });
   return;
  }
  setSaving(true);
  try {
   const { data } = await api.put<WidgetConfig>("/widget/config", { ...config, launcher_label: "" });
   setConfig(data);
   setSavedConfig(data);
  } catch (err) {
   // El backend devuelve mensajes de validación útiles (p. ej. contraste de
   // color insuficiente). Se muestran al usuario en vez de un error genérico.
   toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar la configuración del widget.") });
  } finally { setSaving(false); }
 }

 function handleDiscard() {
  if (savedConfig) {
   setConfig(savedConfig);
   setCaptacionOpen(
    (savedConfig.proactive_message ?? "") !== "" ||
    (savedConfig.suggestions ?? []).length > 0
   );
  }
 }

  if (loading) return <Loading />;

 return (
  <div>
   {subtab === "apariencia" && config && (
    <div className="space-y-4">
     <div className="flex items-center justify-between gap-3 bg-primary/5 border border-primary/15 rounded-xl px-4 py-3">
      <p className="text-13 text-foreground">Los cambios de apariencia se reflejan en la vista previa en vivo.</p>
      <Button variant="outline" size="sm" onClick={onPreview} className="shrink-0 gap-1.5">
       <Eye className="w-3.5 h-3.5" /> Ver vista previa
      </Button>
     </div>
     <div className="space-y-4 min-w-0">

      {/* Identidad */}
      <div className="bg-card border border-border rounded-xl shadow-sm p-5 space-y-4">
       <h3 className="text-13 font-semibold uppercase tracking-wider text-muted-foreground">Identidad</h3>
       <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
        <div>
         <label className="block text-xs font-medium text-muted-foreground mb-1.5">Nombre del chatbot</label>
         <Input value={config.chatbot_name} onChange={(e) => setConfig((c) => c ? { ...c, chatbot_name: e.target.value } : c)} />
        </div>
        <div>
         <label className="block text-xs font-medium text-muted-foreground mb-1.5">Color principal</label>
         <div className="flex items-center gap-2">
          <input type="color" value={config.primary_color} onChange={(e) => setConfig((c) => c ? { ...c, primary_color: e.target.value } : c)}
           className="w-8 h-8 rounded border border-border cursor-pointer shrink-0" />
          <Input value={config.primary_color} onChange={(e) => setConfig((c) => c ? { ...c, primary_color: e.target.value } : c)}
           className="font-mono" />
         </div>
        </div>
       </div>
       <div>
        <label className="block text-xs font-medium text-muted-foreground mb-1.5">Mensaje de bienvenida</label>
        <Input value={config.welcome_message} onChange={(e) => setConfig((c) => c ? { ...c, welcome_message: e.target.value } : c)} />
       </div>
       <div>
        <label className="block text-xs font-medium text-muted-foreground mb-1.5">Posición en pantalla</label>
        <PositionPicker value={config.position} onChange={(pos) => setConfig((c) => c ? { ...c, position: pos } : c)} />
       </div>
       <div>
        <label className="block text-xs font-medium text-muted-foreground mb-1.5">URL del logo / ícono</label>
        <Input
         type="url"
         value={config.logo_url ?? ""}
         onChange={(e) => setConfig((c) => c ? { ...c, logo_url: e.target.value || null } : c)}
         placeholder="https://ejemplo.com/logo.png"
        />
        <p className="text-2xs text-muted-foreground mt-1">
         PNG o SVG cuadrado recomendado (mín. 64×64 px). Reemplaza el ícono de robot cuando el toggle «Mostrar ícono» está activo.
        </p>
       </div>

      </div>

      {/* Apariencia — toggle primario visible, resto colapsado */}
      <div className="bg-card border border-border rounded-xl shadow-sm p-5 space-y-1">
       <h3 className="text-13 font-semibold uppercase tracking-wider text-muted-foreground mb-2">Apariencia</h3>
       <SettingToggle label="Mostrar icono del bot" description="Icono en el header y junto a cada respuesta."
        checked={config.show_bot_icon ?? true} onChange={(v) => setConfig((c) => c ? { ...c, show_bot_icon: v } : c)} />
       <InlineDisclosure label="Más opciones de visualización">
        <SettingToggle label="Mostrar fuentes" description="Muestra las fuentes de conocimiento debajo de cada respuesta."
         checked={config.show_sources} onChange={(v) => setConfig((c) => c ? { ...c, show_sources: v } : c)} />
        <SettingToggle label="Botón de copiar" description="Permite al usuario copiar el texto de cada respuesta."
         checked={config.enable_copy_action ?? true} onChange={(v) => setConfig((c) => c ? { ...c, enable_copy_action: v } : c)} />
        <SettingToggle label="Iconos de valoración (👍 / 👎)" description="El usuario puede valorar cada respuesta del asistente."
         checked={config.enable_feedback_icons ?? true} onChange={(v) => setConfig((c) => c ? { ...c, enable_feedback_icons: v } : c)} />
        <SettingToggle label="Menú de accesibilidad" description="Opción «Accesibilidad» en el menú del widget: tamaño de texto y alto contraste. Si se desactiva, tampoco se muestra el botón de leer en voz alta, sin importar el ajuste siguiente."
         checked={config.enable_accessibility ?? true} onChange={(v) => setConfig((c) => c ? { ...c, enable_accessibility: v } : c)} />
        <SettingToggle label="Leer respuestas en voz alta" description="Muestra un botón para escuchar cada respuesta del asistente (requiere un navegador compatible)."
         checked={config.enable_tts ?? true} onChange={(v) => setConfig((c) => c ? { ...c, enable_tts: v } : c)} />
       </InlineDisclosure>
      </div>

      {/* Conversación */}
      <div className="bg-card border border-border rounded-xl shadow-sm p-5 space-y-1">
       <h3 className="text-13 font-semibold uppercase tracking-wider text-muted-foreground mb-2">Controles de conversación</h3>
       <SettingToggle label="Escalamiento a un humano" description="Permite que el bot ofrezca al usuario hablar con una persona y capture su correo o WhatsApp. Las condiciones que lo activan se definen en Escalamiento."
        checked={config.enable_escalation ?? true} onChange={(v) => setConfig((c) => c ? { ...c, enable_escalation: v } : c)} />
       <SettingToggle label="Botón «Finalizar chat»" description="Muestra un botón para que el usuario cierre y archive la conversación activa."
        checked={config.show_end_chat_button ?? true} onChange={(v) => setConfig((c) => c ? { ...c, show_end_chat_button: v } : c)} />
       <SettingToggle label="Botón «Nueva conversación»" description="Permite al usuario reiniciar el chat sin recargar la página."
        checked={config.show_new_chat_button ?? true} onChange={(v) => setConfig((c) => c ? { ...c, show_new_chat_button: v } : c)} />
       <div className="pt-1">
        <SettingToggle label="Encuesta de satisfacción (CSAT)" description="Al finalizar el chat, muestra una encuesta rápida de valoración y comentario."
         checked={config.enable_csat ?? false} onChange={(v) => setConfig((c) => c ? { ...c, enable_csat: v } : c)} />
       </div>
       {config.enable_csat && (
        <div className="pt-2 pl-1">
         <label className="block text-xs font-medium text-muted-foreground mb-1.5">Pregunta de la encuesta</label>
         <Input
          value={config.csat_question ?? ""}
          onChange={(e) => setConfig((c) => c ? { ...c, csat_question: e.target.value } : c)}
          placeholder="¿Cómo calificarías esta conversación?"
          maxLength={200}
         />
         <p className="text-2xs text-muted-foreground mt-1">{(config.csat_question ?? "").length}/200 caracteres</p>
        </div>
       )}
      </div>

      {/* Captación */}
      <div className="bg-card border border-border rounded-xl shadow-sm p-5">
       <div className="flex items-center justify-between">
        <div>
         <h3 className="text-13 font-semibold uppercase tracking-wider text-muted-foreground">Captación</h3>
         <p className="text-2xs text-muted-foreground mt-0.5">Mensaje proactivo y sugerencias rápidas</p>
        </div>
        <Switch
         checked={captacionOpen}
         onCheckedChange={(v) => {
          setCaptacionOpen(v);
          if (!v) setConfig((c) => c ? { ...c, launcher_label: "", proactive_message: "", suggestions: [] } : c);
         }}
        />
       </div>
       {captacionOpen && (
        <div className="mt-4 space-y-4 border-t border-border pt-4">
         <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">Mensaje proactivo</label>
          <p className="text-2xs text-muted-foreground mb-2">Aparece como burbuja junto al botón cerrado, ~1 s después de cargar. Vacío = desactivado.</p>
          <ProactiveMessageInput value={config.proactive_message ?? ""} onChange={(v) => setConfig((c) => c ? { ...c, proactive_message: v } : c)} />
         </div>
         <div>
          <label className="block text-xs font-medium text-muted-foreground mb-1">Sugerencias rápidas</label>
          <p className="text-2xs text-muted-foreground mb-2">Botones bajo el saludo inicial; desaparecen tras el primer mensaje. Máx. 6.</p>
          <SuggestionsEditor value={config.suggestions ?? []} onChange={(v) => setConfig((c) => c ? { ...c, suggestions: v } : c)} />
         </div>
        </div>
       )}
      </div>
     </div>
    </div>
   )}

   {subtab === "integracion" && (
    <div className="space-y-6">
     <div className="bg-card border border-border rounded-xl shadow-sm p-6">
      <div className="flex flex-col gap-3 mb-4">
       <div className="min-w-0">
        <h3 className="text-15 font-semibold tracking-tight">Código de integración</h3>
        <p className="text-13 text-muted-foreground mt-0.5">Pega este snippet antes del cierre de &lt;/body&gt;.</p>
       </div>
       <div className="grid grid-cols-1 sm:flex sm:justify-end gap-2">
        <Button variant="outline" size="sm" className="gap-1.5 h-8"
         onClick={() => { navigator.clipboard.writeText(currentSnippet); setCopied(true); setTimeout(() => setCopied(false), 2000); }}>
         {copied ? <Check className="w-3.5 h-3.5 text-success" /> : <Copy className="w-3.5 h-3.5" />}
         {copied ? "Copiado" : "Copiar"}
        </Button>
       </div>
      </div>
      <SegmentedControl
       ariaLabel="Formato del snippet"
       value={snippetKind}
       onChange={setSnippetKind}
       options={[
        { value: "script", label: "Script tag" },
        { value: "iframe", label: "iframe" },
       ]}
       className="mb-3"
      />
      <pre className="bg-gray-900 text-gray-300 text-13 p-4 rounded-lg overflow-x-auto font-mono leading-relaxed whitespace-pre-wrap break-all">
       {currentSnippet || '<script src="/widget/chatbot.js" defer></script>'}
      </pre>
      <p className="text-2xs text-muted-foreground mt-2">
       {snippetKind === "script"
        ? "Carga el widget asíncronamente. Detecta automáticamente el dominio y lo valida contra la allowlist."
        : "Útil cuando su sitio tiene CSP estricto que bloquea scripts externos. El iframe es independiente del DOM padre."}
      </p>
     </div>
     <WidgetApiKey config={config} onRegenerated={(c) => { setConfig(c); setSavedConfig(c); }} />
     <DomainAllowlist config={config} setConfig={setConfig} />
    </div>
   )}

   {subtab === "limites" && config && (
    <WidgetUsageCaps config={config} onSaved={(c) => { setConfig(c); setSavedConfig(c); }} />
   )}

   <FloatingSaveBar dirty={isDirty} saving={saving} onSave={handleSave} onDiscard={handleDiscard} />
  </div>
 );
}

//
// Caps anti-abuso aplicados al widget público (independientes del rate limit
// global por IP del sistema). Vivían en /publicacion antes; movidos aquí para
// no duplicar configuración del widget en dos rutas.

function WidgetUsageCaps({
 config, onSaved,
}: {
 config: WidgetConfig;
 onSaved: (cfg: WidgetConfig) => void;
}) {
 const { toast } = useToast();
 const [perSession, setPerSession] = useState<string>(config.max_chats_per_session?.toString() ?? "");
 const [perDay, setPerDay] = useState<string>(config.max_chats_per_day?.toString() ?? "");
 const [saving, setSaving] = useState(false);

 function parseLimit(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  const n = parseInt(t, 10);
  return Number.isFinite(n) && n > 0 ? n : null;
 }

 const dirty = parseLimit(perSession) !== (config.max_chats_per_session ?? null)
  || parseLimit(perDay) !== (config.max_chats_per_day ?? null);

 async function handleSave() {
  setSaving(true);
  try {
   const { data } = await api.put<WidgetConfig>("/widget/config", {
    max_chats_per_session: parseLimit(perSession),
    max_chats_per_day: parseLimit(perDay),
   });
   onSaved(data);
   toast({ type: "success", message: "Límites guardados." });
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudieron guardar los límites.") });
  } finally {
   setSaving(false);
  }
 }

 return (
  <div className="space-y-5">
   <div className="bg-card border border-border rounded-xl shadow-sm p-6 space-y-5">
    <div>
     <h3 className="text-15 font-semibold tracking-tight">Caps anti-abuso</h3>
     <p className="text-13 text-muted-foreground mt-0.5">
      Topes aplicados al widget público. Independientes del rate limit por IP del sistema.
     </p>
    </div>

    <div>
     <label className="block text-xs font-medium text-muted-foreground mb-1.5">Mensajes por sesión</label>
     <Input
      type="number"
      min={1}
      value={perSession}
      onChange={(e) => setPerSession(e.target.value)}
      placeholder="Sin límite"
      disabled={saving}
     />
     <p className="text-2xs text-muted-foreground mt-1">
      Tope por sesión de usuario (ventana de 4h). Vacío = sin límite.
     </p>
    </div>

    <div>
     <label className="block text-xs font-medium text-muted-foreground mb-1.5">Mensajes por día (global)</label>
     <Input
      type="number"
      min={1}
      value={perDay}
      onChange={(e) => setPerDay(e.target.value)}
      placeholder="Sin límite"
      disabled={saving}
     />
     <p className="text-2xs text-muted-foreground mt-1">
      Tope diario sumando TODAS las sesiones del widget.
     </p>
    </div>

    <Button size="sm" onClick={handleSave} disabled={saving || !dirty} className="gap-1.5">
     {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
     Guardar
    </Button>
   </div>
  </div>
 );
}
