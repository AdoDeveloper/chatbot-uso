"use client";

import Link from "next/link";
import { useState } from "react";
import {
  CheckCircle2, Circle, ChevronRight, X, Bot, Upload, ShieldCheck, MessageSquare, Zap,
} from "lucide-react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { useOnboardingStatus, type OnboardingStatus } from "@/hooks/use-onboarding-status";

interface StepDef {
  num: number;
  title: string;
  description: string;
  icon: React.ElementType;
  cta: string;
  href: string;
  /** Función que recibe el status y dice si el paso está completo. */
  isDone: (s: OnboardingStatus) => boolean;
  /** Si el paso está bloqueado porque depende de uno anterior, devuelve el motivo. */
  blockedBecause?: (s: OnboardingStatus) => string | null;
}

const STEPS: StepDef[] = [
  {
    num: 1,
    title: "Conectar un proveedor de IA",
    description: "El bot necesita un modelo (Groq, OpenAI, Gemini...) para generar respuestas. Sin esto nada más funcionará.",
    icon: Bot,
    cta: "Configurar proveedor",
    href: "/dashboard/configuracion",
    isDone: (s) => s.providers_configured,
  },
  {
    num: 2,
    title: "Activar y probar el modelo",
    description: "Marque el proveedor como activo y verifique con un mensaje de prueba que la API key responde.",
    icon: Zap,
    cta: "Activar modelo",
    href: "/dashboard/configuracion",
    isDone: (s) => s.providers_active,
    blockedBecause: (s) => !s.providers_configured ? "Primero conecte un proveedor (paso 1)." : null,
  },
  {
    num: 3,
    title: "Subir el primer documento",
    description: "El chatbot solo responde sobre el contenido que usted le da. PDF, DOCX, URL o FAQ — todos sirven.",
    icon: Upload,
    cta: "Subir documento",
    href: "/dashboard/conocimiento/documentos",
    isDone: (s) => s.sources_uploaded,
    blockedBecause: (s) => !s.providers_active ? "Active un modelo primero (paso 2)." : null,
  },
  {
    num: 4,
    title: "Aprobar el documento",
    description: "Tras la ingestión, revise que el contenido es correcto y apruebe la fuente para que el bot la use.",
    icon: ShieldCheck,
    cta: "Revisar fuentes",
    href: "/dashboard/conocimiento/documentos",
    isDone: (s) => s.sources_approved,
    blockedBecause: (s) => !s.sources_uploaded ? "Suba un documento primero (paso 3)." : null,
  },
  {
    num: 5,
    title: "Probar una pregunta",
    description: "Verifique el flujo completo haciendo una pregunta de prueba al bot. Debe responder usando su documento.",
    icon: MessageSquare,
    cta: "Probar consulta",
    href: "/dashboard/conocimiento/consulta",
    isDone: (s) => s.messages_sent > 0,
    blockedBecause: (s) => !s.sources_approved ? "Aprueba al menos una fuente primero (paso 4)." : null,
  },
];

export function OnboardingWizard() {
  const { status, shouldShow, refresh, dismiss } = useOnboardingStatus();
  const [refreshing, setRefreshing] = useState(false);

  if (!shouldShow || !status) return null;

  async function handleRefresh() {
    setRefreshing(true);
    refresh();
    setTimeout(() => setRefreshing(false), 500);
  }

  const completedCount = STEPS.filter((s) => s.isDone(status!)).length;
  const progressPercent = Math.round((completedCount / STEPS.length) * 100);

  return (
    <Card className="mb-6 overflow-hidden border-primary/30 bg-gradient-to-br from-primary/5 to-brand-green/5">
      {/* Header */}
      <div className="px-6 pt-5 pb-4 border-b border-border/40 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <Bot className="w-4 h-4 text-primary" />
            <h2 className="text-base font-semibold tracking-tight">Bienvenido al panel del chatbot USO</h2>
          </div>
          <p className="text-xs text-muted-foreground">
            Para que el sistema funcione, complete estos {STEPS.length} pasos en orden.
            El proceso suele tomar 5-10 minutos.
          </p>
        </div>
        <button
          onClick={dismiss}
          className="text-xs text-muted-foreground hover:text-foreground transition flex items-center gap-1 shrink-0"
          title="No volver a mostrar este tutorial"
        >
          Saltar tutorial <X className="w-3 h-3" />
        </button>
      </div>

      {/* Progress bar */}
      <div className="px-6 py-3 bg-muted/30 border-b border-border/40">
        <div className="flex items-center justify-between text-xs mb-1.5">
          <span className="font-medium">{completedCount}/{STEPS.length} pasos completados</span>
          <span className="tabular-nums text-muted-foreground">{progressPercent}%</span>
        </div>
        <div className="h-1.5 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full bg-gradient-to-r from-primary to-brand-green rounded-full transition-all duration-500"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

      {/* Steps */}
      <div className="divide-y divide-border/40">
        {STEPS.map((step) => {
          const done = step.isDone(status);
          const blocked = !done && step.blockedBecause?.(status);
          const isCurrent = !done && !blocked;
          const Icon = step.icon;

          return (
            <div
              key={step.num}
              className={`px-4 sm:px-6 py-4 flex flex-col sm:flex-row sm:items-center gap-3 sm:gap-4 transition-colors ${
                isCurrent ? "bg-primary/5" : ""
              }`}
            >
              <div className="flex items-center gap-4 flex-1 min-w-0">
                {/* Number / check */}
                <div className="shrink-0">
                  {done ? (
                    <CheckCircle2 className="w-6 h-6 text-brand-green" />
                  ) : isCurrent ? (
                    <div className="w-6 h-6 rounded-full bg-primary text-primary-foreground flex items-center justify-center text-xs font-bold">
                      {step.num}
                    </div>
                  ) : (
                    <Circle className="w-6 h-6 text-muted-foreground/40" strokeWidth={1.5} />
                  )}
                </div>

                {/* Content */}
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <Icon className={`w-3.5 h-3.5 shrink-0 ${done ? "text-brand-green" : isCurrent ? "text-primary" : "text-muted-foreground/60"}`} />
                    <p className={`text-sm font-medium ${done ? "text-muted-foreground line-through" : "text-foreground"}`}>
                      {step.title}
                    </p>
                  </div>
                  <p className="text-xs text-muted-foreground mt-0.5 line-clamp-2">
                    {blocked ?? step.description}
                  </p>
                </div>
              </div>

              {/* CTA */}
              <div className="shrink-0 pl-10 sm:pl-0">
                {done ? (
                  <span className="text-xs text-brand-green font-medium">Listo</span>
                ) : isCurrent ? (
                  <Link href={step.href}>
                    <Button size="sm" className="gap-1.5">
                      {step.cta} <ChevronRight className="w-3.5 h-3.5" />
                    </Button>
                  </Link>
                ) : (
                  <Button size="sm" variant="ghost" disabled className="gap-1.5 opacity-40">
                    Bloqueado
                  </Button>
                )}
              </div>
            </div>
          );
        })}
      </div>

      {/* Footer con refresh */}
      <div className="px-6 py-3 border-t border-border/40 bg-muted/30 flex items-center justify-between">
        <p className="text-xs text-muted-foreground">
          Después de completar un paso, haga clic en &ldquo;Verificar&rdquo; para actualizar el estado.
        </p>
        <Button size="sm" variant="outline" onClick={handleRefresh} disabled={refreshing}>
          {refreshing ? "Verificando…" : "Verificar progreso"}
        </Button>
      </div>
    </Card>
  );
}
