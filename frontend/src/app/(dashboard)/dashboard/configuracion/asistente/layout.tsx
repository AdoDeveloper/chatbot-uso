"use client";

import { useEffect, useRef, useState } from "react";
import { Bot, Download, Upload } from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage, invalidateApiCache } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import type { ChatbotSettings, WidgetConfig } from "@/types";
import { PageHeader } from "@/components/ui/page-header";
import { Button } from "@/components/ui/button";
import { SETTINGS_DEFAULTS } from "../_lib/tabs";
import { AsistenteFormContext } from "./_lib/asistente-context";
import { AsistenteTabs } from "./_components/AsistenteTabs";

export default function AsistenteLayout({ children }: { children: React.ReactNode }) {
  const { toast } = useToast();
  const { data: settings, loading: loadingSettings, refetch: refetchSettings } = useApi<ChatbotSettings>("/settings");
  const { data: widgetConfig, loading: loadingWidget } = useApi<WidgetConfig>("/widget/config");
  const loading = loadingSettings;
  const [form, setForm] = useState<ChatbotSettings>(SETTINGS_DEFAULTS);
  const [savedForm, setSavedForm] = useState<ChatbotSettings | null>(null);
  const [saving, setSaving] = useState(false);
  const [importing, setImporting] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const [widgetForm, setWidgetForm] = useState<WidgetConfig | null>(null);
  useEffect(() => { if (widgetConfig) setWidgetForm(widgetConfig); }, [widgetConfig]);

  const isDirty = savedForm !== null && JSON.stringify(form) !== JSON.stringify(savedForm);

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
      invalidateApiCache("/settings");
      const { data } = await api.post<ChatbotSettings & { warnings?: string[] }>("/settings/import", fd);
      setForm(data);
      setSavedForm(data);
      refetchSettings();
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
    setSaving(true);
    try {
      invalidateApiCache("/settings");
      const { data } = await api.put<ChatbotSettings & { warnings?: string[] }>("/settings", form);
      setSavedForm(form);
      refetchSettings();
      if (data.warnings?.length) {
        toast({ type: "warning", title: "Guardado con advertencias", message: data.warnings.join(" | ") });
      } else {
        toast({ type: "success", title: "Guardado", message: "Configuración actualizada correctamente." });
      }
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar.") });
    } finally {
      setSaving(false);
    }
  }

  return (
    <div>
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

      <AsistenteTabs />

      <AsistenteFormContext.Provider
        value={{
          form, set, loadingSettings,
          widgetForm, setWidgetForm, widgetConfig: widgetConfig ?? null, loadingWidget,
          isDirty, saving, handleSave, handleDiscard,
        }}
      >
        {children}
      </AsistenteFormContext.Provider>
    </div>
  );
}
