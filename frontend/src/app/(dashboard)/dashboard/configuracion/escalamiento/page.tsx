"use client";

import { useEffect, useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { Mail, Plus, Send, Loader2, Pencil, X, Check, UserRound, Beaker, Trash2, Users } from "lucide-react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { useToast } from "@/components/ui/toast";
import type { EscalationRule, EscalationTrigger, RuleTestResult, TriggerSchemaOut } from "@/types";
import { TRIGGER_LABEL_LONG } from "@/lib/escalation-labels";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Skeleton } from "@/components/ui/skeleton";
import { EmptyState } from "@/components/ui/empty-state";
import { PageHeader } from "@/components/ui/page-header";
import { Switch } from "@/components/ui/switch";
import { Modal } from "@/components/composed/modal";
import { Select, SelectOption } from "@/components/ui/select";

const TRIGGER_LABELS = TRIGGER_LABEL_LONG;


// Los campos vienen del schema que expone el backend (GET /escalation/triggers/schemas), no de un shape fijo.
type TriggerConfig = Record<string, number | string>;

interface RuleForm {
  name: string;
  description: string;
  trigger_type: EscalationTrigger;
  enabled: boolean;
  trigger_config: TriggerConfig;
}

const escalationRuleSchema = z.object({
  name: z.string().min(1, "Nombre es obligatorio"),
  description: z.string(),
  trigger_type: z.enum(["no_answer", "user_request", "negative_feedback", "keyword_detected", "confidence_below", "loop_detected"]),
  enabled: z.boolean(),
  trigger_config: z.record(z.string(), z.union([z.number(), z.string()])),
});

type RuleFormValues = z.infer<typeof escalationRuleSchema>;

function defaultsFromSchema(schema: TriggerSchemaOut | undefined): TriggerConfig {
  if (!schema) return {};
  const out: TriggerConfig = {};
  for (const [key, field] of Object.entries(schema.fields)) {
    out[key] = field.type === "list[str]"
      ? (field.default as string[]).join(", ")
      : (field.default as number);
  }
  return out;
}

const EMPTY_RULE: RuleForm = {
  name: "", description: "", trigger_type: "no_answer", enabled: true,
  trigger_config: {},
};

// Texto de ayuda contextual por campo - no viene del schema del backend, es contenido pedagógico propio de este panel.
const TRIGGER_FIELD_HINTS: Partial<Record<EscalationTrigger, Record<string, string>>> = {
  no_answer: {
    wait_seconds: "Si el bot tarda más de N segundos en responder, se activa el escalamiento.",
  },
  user_request: {
    keywords: "Dejar vacío para escalar ante cualquier solicitud explícita.",
  },
  negative_feedback: {
    threshold: "Escala si la proporción de 👎 en la sesión supera este valor.",
  },
  keyword_detected: {
    keywords: "Si el mensaje del usuario contiene cualquiera de estas palabras, se escala inmediatamente.",
  },
  confidence_below: {
    threshold: "La búsqueda combina texto y significado (RRF); sus puntajes son bajos, no de 0 a 1. Típico: 0.015–0.033.",
    consecutive: "Escala si las últimas N respuestas tuvieron confianza menor al umbral.",
  },
  loop_detected: {
    repetitions: "Escala si el bot repite la misma respuesta esta cantidad de veces consecutivas.",
  },
};

export default function EscalamientoConfigPage() {
  const { toast } = useToast();
  const { data: rulesData, loading, error: rulesError, setData: setRules } =
    useApi<EscalationRule[]>("/escalation/rules");
  const rules = rulesData ?? [];
  const { data: schemasData, error: schemasError } =
    useApi<TriggerSchemaOut[]>("/escalation/triggers/schemas");
  const schemas = schemasData ?? [];
  const schemaFor = (t: EscalationTrigger): TriggerSchemaOut | undefined =>
    schemas.find((s) => s.trigger_type === t);
  const [showRuleModal, setShowRuleModal] = useState(false);
  const [editingRule, setEditingRule] = useState<EscalationRule | null>(null);
  const { register: registerRule, handleSubmit: handleRuleSubmit, watch: watchRule, reset: resetRule, setValue: setRuleValue, formState: { errors: ruleErrors, isSubmitting: saving } } = useForm<RuleFormValues>({
    resolver: zodResolver(escalationRuleSchema),
    defaultValues: EMPTY_RULE,
  });
  const [toggling, setToggling] = useState<string | null>(null);
  const [testing, setTesting] = useState(false);
  const [pinging, setPinging] = useState(false);
  const [confirmDeleteRule, setConfirmDeleteRule] = useState<EscalationRule | null>(null);

  const [showRuleTestModal, setShowRuleTestModal] = useState(false);
  const [ruleTestForm, setRuleTestForm] = useState<RuleForm>(EMPTY_RULE);
  const [ruleTestUserMsg, setRuleTestUserMsg] = useState("");
  const [ruleTestBotAnswers, setRuleTestBotAnswers] = useState("");
  const [ruleTestRagScores, setRuleTestRagScores] = useState("");
  const [ruleTestNoAnswerSec, setRuleTestNoAnswerSec] = useState("");
  const [ruleTestNegRatio, setRuleTestNegRatio] = useState("");
  const [ruleTestRunning, setRuleTestRunning] = useState(false);
  const [ruleTestResult, setRuleTestResult] = useState<RuleTestResult | null>(null);

  useEffect(() => {
    if (rulesError) toast({ type: "error", message: "No se pudo cargar la configuración de escalamiento." });
  }, [rulesError, toast]);

  useEffect(() => {
    if (schemasError) toast({ type: "error", message: "No se pudo cargar el esquema de tipos de activación." });
  }, [schemasError, toast]);

  async function handleToggleRule(rule: EscalationRule) {
    setToggling(rule.id);
    try {
      const { data } = await api.patch<EscalationRule>(`/escalation/rules/${rule.id}`, { enabled: !rule.enabled });
      setRules((prev) => (prev ?? []).map((r) => (r.id === data.id ? data : r)));
      toast({ type: "success", message: `Regla ${data.enabled ? "activada" : "desactivada"}.`, duration: 1500 });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al cambiar el estado de la regla.") });
    } finally { setToggling(null); }
  }

  async function handleSmtpPing() {
    setPinging(true);
    try {
      const { data } = await api.post<{ ok: boolean; error: string | null; latency_ms: number | null }>(
        "/escalation/smtp-ping",
      );
      if (data.ok) {
        toast({ type: "success", message: data.latency_ms != null ? `Email enviado (${data.latency_ms}ms) · revise su bandeja.` : "Email de prueba enviado." });
      } else {
        toast({ type: "error", message: data.error ?? "Error al enviar el email de prueba." });
      }
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo conectar con el servidor SMTP.") });
    } finally { setPinging(false); }
  }

  function serializeTriggerConfig(form: RuleForm): Record<string, unknown> {
    const schema = schemaFor(form.trigger_type);
    const tc = form.trigger_config;
    const splitCsv = (s: string) => s.split(",").map((k) => k.trim()).filter(Boolean);
    if (!schema) return {};
    const out: Record<string, unknown> = {};
    for (const [key, field] of Object.entries(schema.fields)) {
      const raw = tc[key];
      if (field.type === "list[str]") {
        out[key] = typeof raw === "string" ? splitCsv(raw) : (field.default as string[]);
      } else {
        out[key] = typeof raw === "number" ? raw : (field.default as number);
      }
    }
    return out;
  }

  const onSaveRule = handleRuleSubmit(async (data) => {
    try {
      const payload = { ...data, trigger_config: serializeTriggerConfig(data) };
      if (editingRule) {
        const { data: updated } = await api.patch<EscalationRule>(`/escalation/rules/${editingRule.id}`, payload);
        setRules((prev) => (prev ?? []).map((r) => (r.id === updated.id ? updated : r)));
      } else {
        const { data: created } = await api.post<EscalationRule>("/escalation/rules", payload);
        setRules((prev) => [...(prev ?? []), created]);
      }
      toast({ type: "success", message: editingRule ? "Regla actualizada." : "Regla creada." });
      setShowRuleModal(false);
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al guardar la regla.") });
    }
  });

  async function handleDeleteRule(id: string) {
    setToggling(id);
    try {
      await api.delete(`/escalation/rules/${id}`);
      setRules((prev) => (prev ?? []).filter((r) => r.id !== id));
      toast({ type: "success", message: "Regla eliminada." });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al eliminar la regla.") });
    } finally { setToggling(null); }
  }

  async function handleTest() {
    setTesting(true);
    try {
      const { data } = await api.post<{ success: boolean; message: string }>("/escalation/test");
      toast({ type: data.success ? "success" : "error", message: data.message });
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo enviar la prueba. Revise la configuración del canal.") });
    } finally { setTesting(false); }
  }

  async function runRuleTest() {
    setRuleTestRunning(true);
    setRuleTestResult(null);
    try {
      const parseFloats = (s: string) =>
        s.split(",").map((x) => parseFloat(x.trim())).filter((n) => !isNaN(n));
      const parseLines = (s: string) =>
        s.split("\n").map((x) => x.trim()).filter(Boolean);
      const { data } = await api.post<RuleTestResult>("/escalation/rules/test", {
        trigger_type: ruleTestForm.trigger_type,
        trigger_config: serializeTriggerConfig(ruleTestForm),
        context: {
          user_message: ruleTestUserMsg || null,
          bot_answers: parseLines(ruleTestBotAnswers),
          rag_scores: parseFloats(ruleTestRagScores),
          no_answer_seconds: ruleTestNoAnswerSec ? Number(ruleTestNoAnswerSec) : null,
          feedback_negative_ratio: ruleTestNegRatio ? Number(ruleTestNegRatio) : null,
        },
      });
      setRuleTestResult(data);
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "Error al ejecutar la prueba de regla.") });
    } finally {
      setRuleTestRunning(false);
    }
  }

  return (
    <div>
      <PageHeader
        icon={UserRound}
        title="Escalamiento"
        tip="Configura cuándo y cómo el chatbot transfiere conversaciones a un agente humano."
        action={
          <Button variant="outline" size="sm" onClick={handleTest} disabled={testing} className="gap-1.5">
            {testing ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
            Enviar prueba
          </Button>
        }
      />

      {loading ? (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Skeleton className="h-64 w-full" />
          <Skeleton className="h-64 w-full" />
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          {/* Reglas */}
          <Card>
            <CardHeader className="pb-4 border-b">
              <div className="flex flex-col gap-3">
                <div>
                  <CardTitle className="text-15 font-semibold">Reglas de escalamiento</CardTitle>
                  <CardDescription>Condiciones que activan la transferencia</CardDescription>
                </div>
                <div className="grid grid-cols-1 sm:flex sm:justify-end">
                  <Button
                    variant="ghost"
                    size="sm"
                    className="gap-1 text-13 text-primary"
                    onClick={() => { setEditingRule(null); resetRule(EMPTY_RULE); setShowRuleModal(true); }}
                  >
                    <Plus className="w-3.5 h-3.5" /> Agregar
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="pt-4">
              {rules.length === 0 ? (
                <EmptyState icon={Mail} title="Sin reglas" description="Agrega una regla para activar el escalamiento" />
              ) : (
                <ul className="space-y-2.5">
                  {rules.map((rule) => (
                    <li key={rule.id} className="rounded-lg border px-3.5 py-3 bg-muted/30 hover:bg-muted/50 transition-colors">
                      <div className="flex items-start gap-3">
                        <Switch
                          checked={rule.enabled}
                          onCheckedChange={() => handleToggleRule(rule)}
                          disabled={toggling === rule.id}
                          className="shrink-0 mt-0.5"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="text-13 font-medium truncate min-w-0" title={rule.name}>{rule.name}</p>
                            <Badge variant={rule.enabled ? "success" : "secondary"} className="text-3xs shrink-0">
                              {rule.enabled ? "Activa" : "Inactiva"}
                            </Badge>
                          </div>
                          <p className="text-2xs text-muted-foreground mt-0.5">
                            <span className="font-medium">Trigger:</span> {TRIGGER_LABELS[rule.trigger_type]}
                          </p>
                          {rule.description && (
                            <p className="text-2xs text-muted-foreground mt-1 leading-snug break-words">{rule.description}</p>
                          )}
                          {/* Mostrar config relevante, según el schema del trigger */}
                          {rule.trigger_config && Object.keys(rule.trigger_config).length > 0 && (() => {
                            const schema = schemaFor(rule.trigger_type);
                            if (!schema) return null;
                            const tc = rule.trigger_config as Record<string, unknown>;
                            return (
                              <div className="mt-1.5 flex flex-wrap gap-1">
                                {Object.entries(schema.fields).map(([key, field]) => {
                                  const val = tc[key];
                                  if (field.type === "list[str]") {
                                    const arr = Array.isArray(val) ? (val as string[]) : [];
                                    if (arr.length === 0) return null;
                                    return (
                                      <span key={key} className="text-3xs px-1.5 py-0.5 bg-muted rounded font-mono">
                                        {arr.length} {field.label.toLowerCase()}
                                      </span>
                                    );
                                  }
                                  if (typeof val !== "number") return null;
                                  return (
                                    <span key={key} className="text-3xs px-1.5 py-0.5 bg-muted rounded font-mono">
                                      {field.label}: {val}
                                    </span>
                                  );
                                })}
                              </div>
                            );
                          })()}
                        </div>
                        <div className="flex items-center gap-1 shrink-0">
                          <Button
                            variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-foreground"
                            onClick={() => {
                              const schema = schemaFor(rule.trigger_type);
                              const tc = rule.trigger_config as Record<string, unknown>;
                              const config: TriggerConfig = {};
                              if (schema) {
                                for (const [key, field] of Object.entries(schema.fields)) {
                                  const val = tc[key];
                                  if (field.type === "list[str]") {
                                    config[key] = Array.isArray(val)
                                      ? (val as string[]).join(", ")
                                      : typeof val === "string" ? val : (field.default as string[]).join(", ");
                                  } else {
                                    config[key] = typeof val === "number" ? val : (field.default as number);
                                  }
                                }
                              }
                              setEditingRule(rule);
                              resetRule({
                                name: rule.name, description: rule.description,
                                trigger_type: rule.trigger_type, enabled: rule.enabled,
                                trigger_config: config,
                              });
                              setShowRuleModal(true);
                            }}
                          >
                            <Pencil className="w-3 h-3" />
                          </Button>
                          <Button
                            variant="ghost" size="icon" className="h-7 w-7 text-muted-foreground hover:text-destructive"
                            onClick={() => setConfirmDeleteRule(rule)}
                            disabled={toggling === rule.id}
                          >
                            <X className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>

          {/* Destinatarios */}
          <Card>
            <CardHeader className="pb-4 border-b">
              <CardTitle className="text-15 font-semibold">Destinatarios</CardTitle>
              <CardDescription>Quién recibe las notificaciones de escalamiento</CardDescription>
            </CardHeader>
            <CardContent className="pt-4 space-y-4">
              <div className="rounded-lg border bg-muted/30 px-4 py-3 flex gap-3">
                <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center shrink-0">
                  <Users className="w-4 h-4 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                  <p className="text-13 font-medium">Administradores del sistema</p>
                  <p className="text-2xs text-muted-foreground leading-snug mt-0.5">
                    Cuando un usuario acepta ser contactado, el correo se envía automáticamente
                    a todos los usuarios <span className="font-medium">activos</span> registrados en el sistema.
                    Para añadir o quitar destinatarios, gestiona los usuarios desde el menú de Usuarios.
                  </p>
                </div>
              </div>

              <div className="rounded-lg border px-4 py-3 flex items-center justify-between gap-3">
                <div className="flex items-center gap-2.5">
                  <Mail className="w-4 h-4 text-muted-foreground shrink-0" />
                  <div>
                    <p className="text-13 font-medium">Prueba de SMTP</p>
                    <p className="text-2xs text-muted-foreground">Envía un email de prueba a su cuenta para verificar la entrega.</p>
                  </div>
                </div>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={handleSmtpPing}
                  disabled={pinging}
                  className="gap-1.5 shrink-0"
                >
                  {pinging ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                  Probar
                </Button>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {/* Diálogo de regla */}
      <Modal
        open={showRuleModal}
        onClose={() => setShowRuleModal(false)}
        size="lg"
        title={editingRule ? "Editar regla" : "Nueva regla"}
        footer={
          <>
            <Button
              variant="ghost"
              onClick={() => { setRuleTestForm(watchRule()); setRuleTestResult(null); setShowRuleTestModal(true); }}
              disabled={!watchRule("name").trim()}
              className="mr-auto gap-1.5"
              title="Probar la regla con un contexto manual"
            >
              <Beaker className="w-3.5 h-3.5" /> Probar
            </Button>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setShowRuleModal(false)}><X className="w-3.5 h-3.5" /> Cancelar</Button>
            <Button size="sm" onClick={onSaveRule} disabled={saving} className="gap-1.5">
              {saving ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Check className="w-3.5 h-3.5" />}
              Guardar
            </Button>
          </>
        }
      >
        <div className="space-y-4 py-2">
            <div className="space-y-1.5">
              <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Nombre</Label>
              <Input {...registerRule("name")} placeholder="Nombre de la regla" />
              {ruleErrors.name && <p className="text-2xs text-destructive">{ruleErrors.name.message}</p>}
            </div>
            <div className="space-y-1.5">
              <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Descripción</Label>
              <Input {...registerRule("description")} placeholder="Descripción opcional" />
            </div>
            <div className="space-y-1.5">
              <Label className="text-2xs font-semibold text-muted-foreground uppercase tracking-wide">Tipo de activación</Label>
              <Select
                value={watchRule("trigger_type")}
                onChange={(e) => {
                  const t = e.target.value as EscalationTrigger;
                  setRuleValue("trigger_type", t);
                  setRuleValue("trigger_config", defaultsFromSchema(schemaFor(t)), { shouldDirty: true });
                }}
              >
                {(Object.entries(TRIGGER_LABELS) as [EscalationTrigger, string][]).map(([v, l]) => (
                  <SelectOption key={v} value={v}>{l}</SelectOption>
                ))}
              </Select>
            </div>

            {schemaFor(watchRule("trigger_type")) &&
              Object.entries(schemaFor(watchRule("trigger_type"))!.fields).map(([key, field]) => {
                const hint = TRIGGER_FIELD_HINTS[watchRule("trigger_type")]?.[key];
                const currentVal = watchRule(`trigger_config.${key}`);
                return (
                  <div key={key} className="space-y-1.5">
                    <Label className="text-xs font-semibold text-muted-foreground uppercase tracking-wide">{field.label}</Label>
                    {field.type === "list[str]" ? (
                      <Input
                        value={typeof currentVal === "string" ? currentVal : ""}
                        onChange={(e) => setRuleValue(`trigger_config.${key}`, e.target.value, { shouldDirty: true })}
                        placeholder={(field.default as string[]).join(", ")}
                      />
                    ) : (
                      <Input
                        type="number" min={field.min} max={field.max} step={field.step ?? 1}
                        value={typeof currentVal === "number" ? currentVal : (field.default as number)}
                        onChange={(e) => setRuleValue(`trigger_config.${key}`, Number(e.target.value), { shouldDirty: true })}
                      />
                    )}
                    {hint && <p className="text-2xs text-muted-foreground">{hint}</p>}
                  </div>
                );
              })}

            <div className="flex items-center gap-3 rounded-lg border px-3 py-2.5 bg-muted/30">
              <Switch checked={watchRule("enabled")} onCheckedChange={(checked) => setRuleValue("enabled", checked, { shouldDirty: true })} />
              <div>
                <p className="text-13 font-medium">Regla activa</p>
                <p className="text-2xs text-muted-foreground">Se evaluará en cada conversación</p>
              </div>
            </div>
          </div>
        </Modal>

      {/* Confirmación de eliminación */}
      <Modal
        open={!!confirmDeleteRule}
        onClose={() => setConfirmDeleteRule(null)}
        size="sm"
        title="Eliminar regla"
        footer={
          <>
            <Button variant="outline" size="sm" className="gap-1.5" onClick={() => setConfirmDeleteRule(null)}><X className="w-3.5 h-3.5" /> Cancelar</Button>
            <Button variant="destructive" size="sm" className="gap-1.5" onClick={async () => { if (confirmDeleteRule) { setConfirmDeleteRule(null); await handleDeleteRule(confirmDeleteRule.id); } }}>
              <Trash2 className="w-3.5 h-3.5" /> Eliminar
            </Button>
          </>
        }
      >
        <div className="py-2">
          <p className="text-sm text-muted-foreground">¿Eliminar esta regla? Esta acción no se puede deshacer.</p>
          {confirmDeleteRule && (
            <p className="mt-3 text-13 font-medium border-l-2 border-destructive pl-3 break-words">{confirmDeleteRule.name}</p>
          )}
        </div>
      </Modal>

      {/* Test individual de regla */}
      <Modal
        open={showRuleTestModal}
        onClose={() => setShowRuleTestModal(false)}
        size="2xl"
        title={
          <span className="flex items-center gap-2">
            <Beaker className="w-4 h-4 text-primary" />
            Probar regla: {TRIGGER_LABELS[ruleTestForm.trigger_type]}
          </span>
        }
        footer={
          <Button variant="outline" size="sm" onClick={() => setShowRuleTestModal(false)}>Cerrar</Button>
        }
      >
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4 py-2">
            {/* Contexto */}
            <div className="space-y-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Contexto simulado</p>

              {(ruleTestForm.trigger_type === "user_request"
                || ruleTestForm.trigger_type === "keyword_detected") && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Mensaje del usuario</Label>
                  <Input
                    value={ruleTestUserMsg}
                    onChange={(e) => setRuleTestUserMsg(e.target.value)}
                    placeholder="quiero hablar con un agente humano"
                  />
                </div>
              )}

              {ruleTestForm.trigger_type === "no_answer" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Segundos sin respuesta</Label>
                  <Input
                    type="number"
                    min={1}
                    value={ruleTestNoAnswerSec}
                    onChange={(e) => setRuleTestNoAnswerSec(e.target.value)}
                    placeholder="180"
                  />
                </div>
              )}

              {ruleTestForm.trigger_type === "negative_feedback" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Proporción de valoraciones negativas (0–1)</Label>
                  <Input
                    type="number" step={0.05} min={0} max={1}
                    value={ruleTestNegRatio}
                    onChange={(e) => setRuleTestNegRatio(e.target.value)}
                    placeholder="0.6"
                  />
                </div>
              )}

              {ruleTestForm.trigger_type === "confidence_below" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Scores RAG recientes (separados por coma)</Label>
                  <Input
                    value={ruleTestRagScores}
                    onChange={(e) => setRuleTestRagScores(e.target.value)}
                    placeholder="0.015, 0.012, 0.018"
                  />
                  <p className="text-2xs text-muted-foreground">Escala típica del sistema: 0–0.033 (RRF), no 0–1.</p>
                </div>
              )}

              {ruleTestForm.trigger_type === "loop_detected" && (
                <div className="space-y-1.5">
                  <Label className="text-xs">Últimas respuestas del bot (una por línea)</Label>
                  <textarea
                    value={ruleTestBotAnswers}
                    onChange={(e) => setRuleTestBotAnswers(e.target.value)}
                    rows={4}
                    className="w-full px-3 py-2 text-sm border border-border rounded-xl bg-background focus:outline-none focus:ring-2 focus:ring-ring/50 resize-none font-mono"
                    placeholder="No pude encontrar información sobre eso&#10;No pude encontrar información sobre eso&#10;No pude encontrar información sobre eso"
                  />
                </div>
              )}

              <Button
                size="sm"
                onClick={runRuleTest}
                disabled={ruleTestRunning}
                className="gap-1.5"
              >
                {ruleTestRunning ? <Loader2 className="w-3.5 h-3.5 animate-spin" /> : <Send className="w-3.5 h-3.5" />}
                Ejecutar prueba
              </Button>
            </div>

            {/* Resultado */}
            <div className="space-y-3 border-l border-border pl-4">
              <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">Resultado</p>
              {!ruleTestResult ? (
                <p className="text-2xs text-muted-foreground italic">
                  Completa el contexto y presiona &ldquo;Ejecutar prueba&rdquo; para ver si la regla se activaría.
                </p>
              ) : (
                <>
                  <div className={`px-3 py-2 rounded-lg text-sm font-semibold ${
                    ruleTestResult.matches
                      ? "text-warning border border-warning/30"
                      : "bg-brand-green/10 text-brand-green border border-brand-green/30"
                  }`}>
                    {ruleTestResult.matches ? "🔔 La regla se activaría" : "✅ La regla NO se activaría"}
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-1">Detalle</p>
                    <p className="text-sm">{ruleTestResult.detail}</p>
                  </div>
                  <div>
                    <p className="text-xs font-medium text-muted-foreground mb-1">Payload que se enviaría</p>
                    <pre className="text-2xs font-mono bg-muted/50 border border-border rounded-lg p-2 overflow-auto max-h-48">
{JSON.stringify(ruleTestResult.payload_preview, null, 2)}
                    </pre>
                  </div>
                </>
              )}
            </div>
          </div>
        </Modal>
    </div>
  );
}
