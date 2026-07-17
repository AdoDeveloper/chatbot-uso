"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import {
  Shield, ChevronDown, ChevronRight, Play,
  CheckCircle, XCircle, ExternalLink, Save, Loader2,
  Plus, Pencil, Trash2, X, BarChart3,
} from "lucide-react";
import { Modal } from "@/components/composed/modal";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import Link from "next/link";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import { UnpublishedBanner } from "../_lib/tabs";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { PageHeader } from "@/components/ui/page-header";
import { Skeleton } from "@/components/ui/skeleton";

interface InjectionPattern {
  id: string;
  regex: string;
  label: string;
  category: string;
  example: string;
  source: "builtin" | "custom";
  enabled: boolean;
}

interface GuardrailsConfig {
  enabled: boolean;
  max_input_chars: number;
  max_output_tokens: number;
  pii_entities: string[];
  injection_patterns_count: number;
}

interface TestResult {
  passed: boolean;
  reason: string;
  sanitized_text: string;
  matched_label?: string | null;
  matched_category?: string | null;
  matched_pattern?: string | null;
}

const CATEGORY_LABELS: Record<string, string> = {
  override: "Override de instrucciones",
  role: "Secuestro de rol",
  obfuscation: "Ofuscación",
  markup: "Inyección de markup",
  jailbreak: "Jailbreak",
  exfiltration: "Exfiltración del prompt",
};

const ALL_PII: { key: string; label: string; example: string }[] = [
  { key: "PHONE_NUMBER", label: "Teléfonos", example: "+503 7777-7777" },
  { key: "EMAIL_ADDRESS", label: "Correos electrónicos", example: "usuario@dominio.com" },
  { key: "CREDIT_CARD", label: "Tarjetas de crédito", example: "4111 1111 1111 1111" },
  { key: "IBAN_CODE", label: "Cuentas IBAN", example: "DE89 3704 0044 0532 0130 00" },
];

export default function FiltrosPage() {
  const { toast, confirm } = useToast();
  interface CategoryImpact { category: string; count: number }

  const { data: configData, loading: loadingConfig, setData: setConfig } =
    useApi<GuardrailsConfig>("/guardrails/config");
  const { data: patternsData, loading: loadingPatterns, refetch: refetchPatterns, setData: setPatterns } =
    useApi<InjectionPattern[]>("/guardrails/patterns");
  const { data: impactData, loading: loadingImpact } =
    useApi<{ category: string; count: number; sample_label: string | null }[]>("/security/injections/by-category?days=30");
  const patterns = patternsData ?? [];
  const categoryImpact: CategoryImpact[] = (impactData ?? []).map(({ category, count }) => ({ category, count }));
  const [openCategories, setOpenCategories] = useState<Record<string, boolean>>({});

  const [testText, setTestText] = useState("");
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<TestResult | null>(null);

const [patternModalOpen, setPatternModalOpen] = useState(false);
const [editingPatternId, setEditingPatternId] = useState<string | null>(null);
const [impactByLabel, setImpactByLabel] = useState<Record<string, number>>({});
const [loadingImpactId, setLoadingImpactId] = useState<string | null>(null);

const guardrailsSchema = z.object({
  enabled: z.boolean(),
  maxInputChars: z.number().min(100).max(10000),
  maxOutputTokens: z.number().min(64).max(8192),
  piiEntities: z.array(z.string()),
});

type GuardrailsFormValues = z.infer<typeof guardrailsSchema>;

const { handleSubmit: handleGSubmit, watch, reset: resetG, setValue, formState: { isDirty: dirty, isSubmitting: saving } } = useForm<GuardrailsFormValues>({
  resolver: zodResolver(guardrailsSchema),
  defaultValues: { enabled: true, maxInputChars: 2000, maxOutputTokens: 1024, piiEntities: [] },
});

const patternSchema = z.object({
  regex: z.string().min(1, "Regex es obligatorio"),
  label: z.string().min(1, "Nombre es obligatorio"),
  category: z.string(),
  example: z.string().optional(),
  enabled: z.boolean(),
});

type PatternFormValues = z.infer<typeof patternSchema>;

const { register: registerPattern, handleSubmit: handlePatternSubmit, reset: resetPattern, formState: { errors: patternErrors, isSubmitting: patternSaving } } = useForm<PatternFormValues>({
  resolver: zodResolver(patternSchema),
  defaultValues: { regex: "", label: "", category: "Custom", example: "", enabled: true },
});

  useEffect(() => {
    if (!configData) return;
    resetG({ enabled: configData.enabled, maxInputChars: configData.max_input_chars, maxOutputTokens: configData.max_output_tokens, piiEntities: configData.pii_entities });
  }, [configData, resetG]);

  const onSaveConfig = handleGSubmit(async (data) => {
    try {
      await api.patch("/guardrails/config", {
        guardrails_enabled: data.enabled,
        max_input_chars: data.maxInputChars,
        max_output_tokens: data.maxOutputTokens,
        pii_entities: data.piiEntities,
      });
      const saved = { enabled: data.enabled, max_input_chars: data.maxInputChars, max_output_tokens: data.maxOutputTokens, pii_entities: data.piiEntities };
      setConfig((c) => c ? { ...c, ...saved } : c);
      resetG({ ...data });
      toast({ type: "success", message: "Configuración de filtros guardada." });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al guardar la configuración.") });
    }
  });

  function togglePii(key: string) {
    const current = watch("piiEntities");
    const next = current.includes(key) ? current.filter((k) => k !== key) : [...current, key];
    setValue("piiEntities", next, { shouldDirty: true });
  }

  async function runTest() {
    if (!testText.trim()) return;
    setTesting(true);
    setTestResult(null);
    try {
      const { data } = await api.post<TestResult>("/guardrails/test", { text: testText });
      setTestResult(data);
    } catch {
      setTestResult({ passed: false, reason: "Error al probar el texto", sanitized_text: "" });
    } finally {
      setTesting(false);
    }
  }

  function openCreatePattern() {
    setEditingPatternId(null);
    resetPattern({ regex: "", label: "", category: "Custom", example: "", enabled: true });
    setPatternModalOpen(true);
  }

  function openEditPattern(p: InjectionPattern) {
    if (p.source !== "custom") {
      toast({ type: "info", message: "Los patrones built-in no se pueden editar. Crea uno custom." });
      return;
    }
    setEditingPatternId(p.id);
    resetPattern({
      regex: p.regex, label: p.label,
      category: p.category, example: p.example, enabled: p.enabled,
    });
    setPatternModalOpen(true);
  }

  const onSavePattern = handlePatternSubmit(async (data) => {
    try {
      const body = {
        regex: data.regex,
        label: data.label,
        category: data.category || "Custom",
        example: data.example,
        enabled: data.enabled,
      };
      if (editingPatternId) {
        await api.patch(`/guardrails/patterns/${editingPatternId}`, body);
        toast({ type: "success", message: "Patrón actualizado." });
      } else {
        await api.post("/guardrails/patterns", body);
        toast({ type: "success", message: "Patrón creado." });
      }
      setPatternModalOpen(false);
      await refetchPatterns();
    } catch (err: unknown) {
      toast({ type: "error", message: getErrorMessage(err, "Error al guardar el patrón.") });
    }
  });

  async function deletePattern(p: InjectionPattern) {
    if (p.source !== "custom") return;
    const ok = await confirm({
      title: `¿Eliminar el patrón "${p.label}"?`,
      message: "Esta acción no se puede deshacer.",
      confirmText: "Eliminar",
      variant: "danger",
    });
    if (!ok) return;
    try {
      await api.delete(`/guardrails/patterns/${p.id}`);
      toast({ type: "success", message: "Patrón eliminado." });
      setPatterns((prev) => (prev ?? []).filter((x) => x.id !== p.id));
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al eliminar el patrón.") });
    }
  }

  async function loadImpact(p: InjectionPattern) {
    setLoadingImpactId(p.id);
    try {
      const { data } = await api.get<{ blocks: number; days: number }>(`/guardrails/patterns/${p.id}/impact?days=7`);
      setImpactByLabel((prev) => ({ ...prev, [p.label]: data.blocks }));
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo calcular el impacto.") });
    } finally {
      setLoadingImpactId(null);
    }
  }

  const grouped = patterns.reduce<Record<string, InjectionPattern[]>>((acc, p) => {
    (acc[p.category] ||= []).push(p);
    return acc;
  }, {});

  const impactByCategory = Object.fromEntries(categoryImpact.map((c) => [c.category, c.count]));

  return (
    <div>
      <UnpublishedBanner />
      <PageHeader
        icon={Shield}
        title="Filtros de seguridad"
        tip="Filtros de contenido no permitido, redacción de datos personales y validación de mensajes."
      />

      <>
        {/* Config editable */}
        {loadingConfig ? (
          <Card className="mb-6">
            <CardHeader className="pb-3 border-b">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-3 w-72 mt-2" />
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <Skeleton className="h-14 w-full rounded-lg" />
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <Skeleton className="h-16 w-full" />
                <Skeleton className="h-16 w-full" />
              </div>
            </CardContent>
          </Card>
        ) : (
          <Card className="mb-6">
            <CardHeader className="pb-3 border-b">
              <div className="flex flex-col gap-3">
                <div>
                  <CardTitle className="text-15 font-semibold">Configuración</CardTitle>
                  <p className="text-2xs text-muted-foreground mt-0.5">Interruptores y límites del sistema de filtros.</p>
                </div>
                {dirty && (
                  <div className="grid grid-cols-1 sm:flex sm:justify-end">
                    <Button size="sm" onClick={onSaveConfig} disabled={saving} className="gap-1.5">
                      {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                      Guardar
                    </Button>
                  </div>
                )}
              </div>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              {/* Master toggle */}
              <div className="flex items-center justify-between rounded-lg border px-4 py-3 bg-muted/20">
                <div>
                  <p className="text-13 font-medium">Guardrails activos</p>
                  <p className="text-2xs text-muted-foreground">Desactivar solo para diagnóstico. No recomendado en producción.</p>
                </div>
                <Switch
                  checked={watch("enabled")}
                  onCheckedChange={(v) => setValue("enabled", v, { shouldDirty: true })}
                />
              </div>

              {/* Numeric limits */}
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="block text-2xs font-semibold text-muted-foreground uppercase tracking-wide">
                    Máx. caracteres de entrada
                  </label>
                  <Input
                    type="number"
                    min={100}
                    max={10000}
                    step={100}
                    value={watch("maxInputChars")}
                    onChange={(e) => setValue("maxInputChars", Number(e.target.value), { shouldDirty: true })}
                  />
                  <p className="text-2xs text-muted-foreground">Mensajes más largos serán rechazados.</p>
                </div>
                <div className="space-y-1.5">
                  <label className="block text-xs font-semibold text-muted-foreground uppercase tracking-wide">
                    Máx. tokens de salida
                  </label>
                  <Input
                    type="number"
                    min={64}
                    max={8192}
                    step={64}
                    value={watch("maxOutputTokens")}
                    onChange={(e) => setValue("maxOutputTokens", Number(e.target.value), { shouldDirty: true })}
                  />
                  <p className="text-2xs text-muted-foreground">Limita el largo de respuesta del modelo.</p>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

          {/* PII editable */}
          {loadingConfig ? (
          <Card className="mb-6">
            <CardHeader className="pb-3 border-b">
              <Skeleton className="h-5 w-56" />
              <Skeleton className="h-3 w-80 mt-2" />
            </CardHeader>
            <CardContent className="pt-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                <Skeleton className="h-14 w-full rounded-md" />
                <Skeleton className="h-14 w-full rounded-md" />
                <Skeleton className="h-14 w-full rounded-md" />
                <Skeleton className="h-14 w-full rounded-md" />
              </div>
            </CardContent>
          </Card>
          ) : (
          <Card className="mb-6">
            <CardHeader className="pb-3 border-b">
              <CardTitle className="text-15 font-semibold">Datos personales a proteger</CardTitle>
              <p className="text-2xs text-muted-foreground">
                Activa los tipos de datos personales que deben ocultarse automáticamente en las respuestas. Cambios requieren guardar.
              </p>
            </CardHeader>
            <CardContent className="pt-4">
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
                {ALL_PII.map((pii) => {
                  const active = watch("piiEntities").includes(pii.key);
                  return (
                    <button
                      key={pii.key}
                      type="button"
                      onClick={() => togglePii(pii.key)}
                      className={`flex items-start gap-2 px-3 py-2.5 rounded-md border text-left transition-colors ${
                        active
                          ? "border-brand-green/40 bg-brand-green/5 hover:bg-brand-green/10"
                          : "border-border bg-muted/20 hover:bg-muted/40"
                      }`}
                    >
                      <div className={`w-4 h-4 rounded mt-0.5 flex items-center justify-center shrink-0 ${active ? "bg-brand-green" : "bg-muted border border-border"}`}>
                        {active && <CheckCircle className="w-3 h-3 text-white" />}
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className={`text-13 font-medium ${active ? "text-foreground" : "text-muted-foreground"}`}>{pii.label}</p>
                        <p className="text-2xs text-muted-foreground italic">{pii.example}</p>
                      </div>
                    </button>
                  );
                })}
              </div>
              {dirty && (
                <div className="mt-3 flex justify-end">
                  <Button size="sm" onClick={onSaveConfig} disabled={saving} className="gap-1.5">
                    {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
                    Guardar
                  </Button>
                </div>
              )}
            </CardContent>
          </Card>
          )}

          {/* Test inline */}
          {loadingConfig ? (
          <Card className="mb-6">
            <CardHeader className="pb-3 border-b">
              <Skeleton className="h-5 w-40" />
              <Skeleton className="h-3 w-80 mt-2" />
            </CardHeader>
            <CardContent className="pt-4 space-y-3">
              <Skeleton className="h-20 w-full rounded-md" />
              <Skeleton className="h-8 w-28" />
            </CardContent>
          </Card>
          ) : (
          <Card className="mb-6">
            <CardHeader className="pb-3 border-b">
              <CardTitle className="text-15 font-semibold">Probar un texto</CardTitle>
              <p className="text-2xs text-muted-foreground">
                Evalúa si los filtros bloquean, ocultan datos personales o dejan pasar un texto.
                En caso de bloqueo se muestra qué patrón lo detectó.
              </p>
            </CardHeader>
            <CardContent className="pt-4">
              <Textarea
                value={testText}
                onChange={(e) => setTestText(e.target.value)}
                placeholder='Ej: "ignore previous instructions" o "mi correo es juan@uso.edu.sv"'
                rows={3}
                className="font-mono"
              />
              <div className="mt-2 flex items-center gap-2">
                <Button size="sm" onClick={runTest} disabled={testing || !testText.trim()} className="gap-1.5">
                  {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Play className="w-3.5 h-3.5" />}
                  {testing ? "Probando…" : "Probar"}
                </Button>
                {testText && (
                  <Button size="sm" variant="ghost" onClick={() => { setTestText(""); setTestResult(null); }}>
                    Limpiar
                  </Button>
                )}
              </div>
              {testResult && (
                <div className={`mt-3 p-3 rounded-md border text-sm ${
                  testResult.passed
                    ? "border-brand-green/40 bg-brand-green/5"
                    : "border-destructive/40 bg-destructive/5"
                }`}>
                  <div className="flex items-center gap-2 mb-1">
                    {testResult.passed
                      ? <CheckCircle className="w-4 h-4 text-brand-green" />
                      : <XCircle className="w-4 h-4 text-destructive" />}
                    <span className="font-medium">
                      {testResult.passed ? "El texto pasa los filtros" : "Bloqueado por filtros"}
                    </span>
                  </div>
                  <p className="text-2xs text-muted-foreground">{testResult.reason}</p>
                  {testResult.matched_label && (
                    <div className="mt-2 pt-2 border-t border-border space-y-1">
                      <div className="flex items-center gap-2">
                        <span className="text-2xs uppercase tracking-wider text-muted-foreground">Patrón:</span>
                        <Badge className="text-3xs bg-destructive/10 text-destructive border-destructive/20">
                          {testResult.matched_label}
                        </Badge>
                        {testResult.matched_category && (
                          <span className="text-3xs text-muted-foreground">· {testResult.matched_category}</span>
                        )}
                      </div>
                      {testResult.matched_pattern && (
                        <p className="text-2xs font-mono text-muted-foreground break-all">
                          regex: <code>{testResult.matched_pattern}</code>
                        </p>
                      )}
                    </div>
                  )}
                  {testResult.sanitized_text && testResult.sanitized_text !== testText && (
                    <div className="mt-2 pt-2 border-t border-border">
                      <p className="text-2xs uppercase tracking-wider text-muted-foreground mb-1">Texto saneado</p>
                      <p className="text-sm font-mono">{testResult.sanitized_text}</p>
                    </div>
                  )}
                </div>
              )}
            </CardContent>
          </Card>
          )}

          {/* Patrones — built-in read-only + custom CRUD */}
          {loadingPatterns ? (
          <Card className="mb-6">
            <CardHeader className="pb-3 border-b">
              <Skeleton className="h-5 w-48" />
              <Skeleton className="h-3 w-80 mt-2" />
            </CardHeader>
            <CardContent className="pt-4 space-y-2">
              <Skeleton className="h-10 w-full rounded-md" />
              <Skeleton className="h-10 w-full rounded-md" />
              <Skeleton className="h-10 w-full rounded-md" />
              <Skeleton className="h-10 w-full rounded-md" />
            </CardContent>
          </Card>
          ) : (
          <Card className="mb-6">
            <CardHeader className="pb-3 border-b">
              <div className="flex flex-col gap-3">
                <div>
                  <CardTitle className="text-15 font-semibold">Patrones de bloqueo</CardTitle>
                  <p className="text-2xs text-muted-foreground mt-0.5">
                    {patterns.length} reglas activas. Los <b>built-in</b> son definidos por el sistema; los <b>custom</b> los crea y edita usted.
                  </p>
                </div>
                <div className="grid grid-cols-1 sm:flex sm:items-center sm:justify-end gap-2">
                  <Badge variant="outline" className="text-3xs justify-center sm:justify-start">{patterns.length} patrones</Badge>
                  <Button size="sm" onClick={openCreatePattern} className="gap-1.5 h-7">
                    <Plus className="w-3.5 h-3.5" /> Nuevo patrón
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-4">
              {patterns.length === 0 ? (
                <p className="text-sm text-muted-foreground">No se pudieron cargar los patrones.</p>
              ) : (
                <div className="space-y-1">
                  {Object.entries(grouped).map(([cat, items]) => {
                    const open = openCategories[cat] ?? false;
                    const blocked = impactByCategory[cat] ?? 0;
                    return (
                      <div key={cat} className="border border-border rounded-md overflow-hidden">
                        <button
                          type="button"
                          onClick={() => setOpenCategories((s) => ({ ...s, [cat]: !s[cat] }))}
                          className="w-full flex items-center justify-between px-3 py-2 bg-muted/30 hover:bg-muted/50 transition-colors"
                        >
                          <div className="flex items-center gap-2">
                            {open ? <ChevronDown className="w-3.5 h-3.5" /> : <ChevronRight className="w-3.5 h-3.5" />}
                            <span className="text-13 font-medium">{CATEGORY_LABELS[cat] ?? cat}</span>
                            <Badge variant="outline" className="text-3xs tabular-nums">{items.length} patrones</Badge>
                          </div>
                          {blocked > 0 && (
                            <Badge className="text-3xs tabular-nums bg-destructive/15 text-destructive border-destructive/30">
                              {blocked} bloqueo{blocked === 1 ? "" : "s"} (30d)
                            </Badge>
                          )}
                        </button>
                        {open && (
                          <div className="divide-y border-t border-border max-h-105 overflow-y-auto">
                            {items.map((p) => {
                              const isCustom = p.source === "custom";
                              const impact = impactByLabel[p.label];
                              return (
                                <div key={p.id} className="px-3 py-2.5 flex items-start gap-3 group">
                                  <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-2 flex-wrap">
                                      <p className="text-13 font-medium">{p.label}</p>
                                      <Badge
                                        className={`text-3xs ${
                                          isCustom
                                            ? "text-warning border-warning/30"
                                            : "bg-muted text-muted-foreground border-border"
                                        }`}
                                      >
                                        {isCustom ? "custom" : "built-in"}
                                      </Badge>
                                      {!p.enabled && (
                                        <Badge className="text-3xs bg-muted text-muted-foreground border-border">
                                          Deshabilitado
                                        </Badge>
                                      )}
                                      {impact != null && (
                                        <Badge className="text-3xs bg-destructive/10 text-destructive border-destructive/20 tabular-nums">
                                          {impact} bloqueo{impact === 1 ? "" : "s"} (7d)
                                        </Badge>
                                      )}
                                    </div>
                                    <p className="text-2xs font-mono text-muted-foreground mt-0.5 break-all">{p.regex}</p>
                                    {p.example && (
                                      <p className="text-2xs text-muted-foreground mt-0.5 italic">Ej: {p.example}</p>
                                    )}
                                  </div>
                                  <div className="flex items-center gap-0.5 shrink-0 opacity-60 group-hover:opacity-100 transition-opacity">
                                    <Button
                                      variant="ghost"
                                      size="icon-xs"
                                      onClick={() => loadImpact(p)}
                                      disabled={loadingImpactId === p.id}
                                      title="Calcular bloqueos en últimos 7 días"
                                      className="text-muted-foreground hover:text-primary"
                                    >
                                      {loadingImpactId === p.id ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <BarChart3 className="w-3.5 h-3.5" />}
                                    </Button>
                                    {isCustom && (
                                      <>
                                        <Button
                                          variant="ghost"
                                          size="icon-xs"
                                          onClick={() => openEditPattern(p)}
                                          title="Editar"
                                          className="text-muted-foreground hover:text-primary"
                                        >
                                          <Pencil className="w-3.5 h-3.5" />
                                        </Button>
                                        <Button
                                          variant="ghost"
                                          size="icon-xs"
                                          onClick={() => deletePattern(p)}
                                          title="Eliminar"
                                          className="text-muted-foreground hover:text-destructive"
                                        >
                                          <Trash2 className="w-3.5 h-3.5" />
                                        </Button>
                                      </>
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>
          )}

          {/* Log de detecciones */}
          {loadingImpact ? (
          <Card>
            <CardContent className="py-5 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <Skeleton className="w-5 h-5 rounded" />
                <div className="space-y-1.5">
                  <Skeleton className="h-4 w-40" />
                  <Skeleton className="h-3 w-72" />
                </div>
              </div>
              <Skeleton className="h-8 w-24" />
            </CardContent>
          </Card>
          ) : (
          <Card>
            <CardContent className="py-5 flex items-center justify-between gap-4">
              <div className="flex items-center gap-3">
                <Shield className="w-5 h-5 text-muted-foreground shrink-0" />
                <div>
                  <p className="text-13 font-medium">Log de detecciones</p>
                  <p className="text-2xs text-muted-foreground mt-0.5">
                    El historial completo de prompts bloqueados vive en Actividad → Inyecciones.
                  </p>
                </div>
              </div>
              <Link href="/dashboard/actividad/inyecciones">
                <Button variant="outline" size="sm" className="gap-1.5 shrink-0">
                  Actividad
                  <ExternalLink className="w-3.5 h-3.5" />
                </Button>
              </Link>
            </CardContent>
          </Card>
          )}
      </>

      {/* Modal CRUD de patrón custom */}
      <Modal
        open={patternModalOpen}
        onClose={() => { if (!patternSaving) setPatternModalOpen(false); }}
        size="lg"
        title={
          <span className="flex items-center gap-2">
            <Shield className="w-4 h-4 text-primary" />
            {editingPatternId ? "Editar patrón custom" : "Nuevo patrón custom"}
          </span>
        }
        footer={
          <>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setPatternModalOpen(false)} type="button" disabled={patternSaving}>
              <X className="w-3.5 h-3.5" /> Cancelar
            </Button>
            <Button size="sm" type="submit" disabled={patternSaving} className="gap-1.5" form="pattern-form">
              {patternSaving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Save className="w-3.5 h-3.5" />}
              {editingPatternId ? "Guardar" : "Crear"}
            </Button>
          </>
        }
      >
        <form id="pattern-form" onSubmit={onSavePattern}>
          <div className="space-y-3 py-2">
            <div className="space-y-1.5">
              <Label className="text-2xs font-semibold uppercase tracking-wide">Regex</Label>
              <Input {...registerPattern("regex")} placeholder="^(eval|exec)\(" className="font-mono text-sm" />
              {patternErrors.regex && <p className="text-2xs text-destructive">{patternErrors.regex.message}</p>}
              <p className="text-2xs text-muted-foreground">No distingue mayúsculas ni minúsculas. Probar primero con el panel de prueba antes de guardar.</p>
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold uppercase tracking-wide">Nombre</Label>
              <Input {...registerPattern("label")} placeholder="Ej: Bloque de exec/eval" />
              {patternErrors.label && <p className="text-2xs text-destructive">{patternErrors.label.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold uppercase tracking-wide">Categoría</Label>
              <Input {...registerPattern("category")} placeholder="Custom" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-xs font-semibold uppercase tracking-wide">Ejemplo (opcional)</Label>
              <Input {...registerPattern("example")} placeholder="Texto de ejemplo que sería bloqueado" />
            </div>
            <label className="flex items-center gap-2 text-sm cursor-pointer select-none">
              <input type="checkbox" {...registerPattern("enabled")} className="h-3.5 w-3.5 accent-primary" />
              <span>Patrón activo (se evalúa en cada mensaje)</span>
            </label>
          </div>
        </form>
      </Modal>
    </div>
  );
}
