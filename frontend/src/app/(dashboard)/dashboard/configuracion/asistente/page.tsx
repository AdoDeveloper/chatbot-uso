"use client";

import { useEffect, useRef, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import Link from "next/link";
import { Bot, Shield, ChevronRight, Download, Upload, Eye, Palette, Code2, Gauge } from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import type { ChatbotSettings, WidgetConfig } from "@/types";
import { Skeleton } from "@/components/ui/skeleton";
import { UnderlineTabs } from "@/components/composed/underline-tabs";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import {
 PromptTab, ParamsTab, PlaygroundTab, WidgetTab, FloatingSaveBar, SETTINGS_DEFAULTS, UnpublishedBanner,
} from "../_lib/tabs";

// Asistente reúne todo lo que define al chatbot: cómo piensa (prompt/RAG) y
// cómo se ve/comporta (apariencia/integración/límites, antes "Widget" era una
// sección aparte con su propio preview estático desactualizado). Una sola
// fila de tabs y un único preview funcional compartido.
const TABS = [
 { value: "apariencia",  label: "Apariencia",   icon: Palette },
 { value: "prompt",      label: "Prompt",       icon: Bot },
 { value: "integracion", label: "Integración",  icon: Code2 },
 { value: "limites",     label: "Límites",      icon: Gauge },
 { value: "previsualizar", label: "Previsualizar", icon: Eye },
] as const;

type TabId = typeof TABS[number]["value"];

function isTabId(value: string | null): value is TabId {
 return TABS.some((t) => t.value === value);
}

export default function AsistentePage() {
 const { toast } = useToast();
 const router = useRouter();
 const searchParams = useSearchParams();
 const initialTab = searchParams.get("tab");
 const [tab, setTab] = useState<TabId>(isTabId(initialTab) ? initialTab : "apariencia");

  const { data: settings, loading: loadingSettings } = useApi<ChatbotSettings>("/settings");
  const { data: widgetConfig, loading: loadingWidget } = useApi<WidgetConfig>("/widget/config");
  const { data: deployedData, loading: loadingDeployed } = useApi<WidgetConfig>("/versions/deploy/config");
  const deployedWidgetConfig = deployedData && Object.keys(deployedData).length > 0 ? deployedData : null;
  const loading = loadingSettings;
 const [form, setForm] = useState<ChatbotSettings>(SETTINGS_DEFAULTS);
 const [savedForm, setSavedForm] = useState<ChatbotSettings | null>(null);
 const [saving, setSaving] = useState(false);
 const [importing, setImporting] = useState(false);
 const fileInputRef = useRef<HTMLInputElement>(null);

 // Estado editable del config del widget, elevado aquí para que el formulario
 // de Apariencia (WidgetTab) y el preview funcional (PlaygroundTab) compartan
 // el MISMO objeto: así los cambios de apariencia se ven en vivo en el preview.
 const [widgetForm, setWidgetForm] = useState<WidgetConfig | null>(null);
 useEffect(() => { if (widgetConfig) setWidgetForm(widgetConfig); }, [widgetConfig]);

 const isDirty = savedForm !== null && JSON.stringify(form) !== JSON.stringify(savedForm);

 useEffect(() => {
  const urlTab = searchParams.get("tab");
  if (isTabId(urlTab) && urlTab !== tab) setTab(urlTab);
  // eslint-disable-next-line react-hooks/exhaustive-deps
 }, [searchParams]);

 function selectTab(value: TabId) {
  setTab(value);
  router.replace(`/dashboard/configuracion/asistente?tab=${value}`, { scroll: false });
 }

 async function handleExport() {
  try {
   const res = await api.get("/settings/export", { responseType: "blob" });
   const url = URL.createObjectURL(res.data as Blob);
   const a = document.createElement("a");
   const cd = (res.headers["content-disposition"] as string | undefined) ?? "";
   const match = cd.match(/filename="?([^"]+)"?/);
   a.href = url;
   a.download = match?.[1] ?? `chatbot-settings-${new Date().toISOString().slice(0, 10)}.json`;
   a.click();
   URL.revokeObjectURL(url);
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo exportar la configuración.") });
  }
 }

 async function handleImport(e: React.ChangeEvent<HTMLInputElement>) {
  const file = e.target.files?.[0];
  if (!file) return;
  setImporting(true);
  try {
   const fd = new FormData();
   fd.append("file", file);
   const { data } = await api.post<ChatbotSettings & { warnings?: string[] }>("/settings/import", fd);
   setForm(data);
   setSavedForm(data);
   if (data.warnings?.length) {
    toast({ type: "warning", title: "Importado con advertencias", message: data.warnings.join(" | ") });
   } else {
    toast({ type: "success", title: "Configuración importada", message: "Los ajustes se han aplicado correctamente." });
   }
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo importar el archivo. Verifique que sea una exportación válida.") });
  } finally {
   setImporting(false);
   if (fileInputRef.current) fileInputRef.current.value = "";
  }
 }

 // Cuando llega la configuración del backend, inicializa el formulario editable
 useEffect(() => {
  if (settings) { setForm(settings); setSavedForm(settings); }
 }, [settings]);

 const set = (k: keyof ChatbotSettings, v: unknown) =>
  setForm((f) => ({ ...f, [k]: v }));

 function handleDiscard() { if (savedForm) setForm(savedForm); }

 async function handleSave() {
  if (!form.chatbot_name?.trim()) {
   toast({ type: "error", message: "El nombre del chatbot no puede estar vacío." });
   return;
  }
  setSaving(true);
  try {
   const { data } = await api.put<ChatbotSettings & { warnings?: string[] }>("/settings", form);
   setSavedForm(form);
   if (data.warnings?.length) {
    toast({ type: "warning", title: "Guardado con advertencias", message: data.warnings.join(" | ") });
   } else {
    toast({ type: "success", title: "Guardado", message: "Configuración actualizada correctamente." });
   }
  } catch (err) {
   toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar.") });
  } finally { setSaving(false); }
 }

 return (
  <div>
   <UnpublishedBanner />
   <PageHeader
    icon={Bot}
    title="Asistente"
    tip="Identidad, apariencia, prompt maestro y parámetros del motor RAG."
    action={
     <>
      <input ref={fileInputRef} type="file" accept=".json" className="hidden" onChange={handleImport} />
      <Button variant="outline" size="sm" className="gap-1.5" onClick={() => fileInputRef.current?.click()} disabled={importing || loading}>
       <Upload className="w-3.5 h-3.5" />
       {importing ? "Importando…" : "Importar"}
      </Button>
      <Button variant="outline" size="sm" className="gap-1.5" onClick={handleExport} disabled={loading}>
       <Download className="w-3.5 h-3.5" />
       Exportar
      </Button>
     </>
    }
   />

   {/* Navegación de sección: tabs underline (Regla 3), una sola fila para
       todo lo que define al chatbot. El switch Pruebas/Producción vive
       dentro del preview, no aquí. */}
   <UnderlineTabs
    tabs={TABS.map((t) => ({ ...t, onClick: () => selectTab(t.value) }))}
    activeValue={tab}
    scrollable
   />

    {tab === "previsualizar" ? (
      loadingWidget || loadingDeployed ? (
       <Skeleton className="h-[580px] w-full" />
      ) : (
     <PlaygroundTab
      settings={form}
      savedSettings={savedForm}
      widgetConfig={widgetForm ?? widgetConfig}
      deployedWidgetConfig={deployedWidgetConfig}
     />
      )
    ) : tab === "prompt" ? (
      loadingSettings ? (
       <div className="space-y-4 py-8">
        {[1,2,3,4].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
       </div>
      ) : (
     <>
      <PromptTab form={form} set={set} />
      <div className="my-6 border-t" />
      <ParamsTab form={form} set={set} />
      <div className="my-6 border-t" />
      <div>
       <Link href="/dashboard/configuracion/filtros">
       <div className="flex items-center justify-between px-4 py-3 rounded-xl border border-border bg-card hover:bg-muted/40 transition-colors cursor-pointer group">
        <div className="flex items-center gap-3">
         <div className="w-8 h-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
          <Shield className="w-4 h-4 text-primary" />
         </div>
         <div>
          <p className="text-13 font-medium text-foreground">Filtros de seguridad</p>
          <p className="text-2xs text-muted-foreground">Filtros de contenido, protección de datos personales y probador de texto</p>
         </div>
        </div>
        <ChevronRight className="w-4 h-4 text-muted-foreground group-hover:text-foreground transition-colors" />
       </div>
      </Link>
      </div>
     </>
      )
    ) : (
      loadingSettings ? (
       <div className="space-y-4 py-8">
        {[1,2,3,4].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
       </div>
      ) : loadingWidget ? (
       <div className="space-y-4 py-8">
        {[1,2,3].map((i) => <Skeleton key={i} className="h-12 w-full" />)}
       </div>
      ) : (
     <WidgetTab subtab={tab} onPreview={() => selectTab("previsualizar")} config={widgetForm} setConfig={setWidgetForm} />
      )
    )}

   {tab === "prompt" && (
    <FloatingSaveBar dirty={isDirty} saving={saving} onSave={handleSave} onDiscard={handleDiscard} />
   )}
  </div>
 );
}
