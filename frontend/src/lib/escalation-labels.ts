import type { EscalationTrigger } from "@/types";

export const TRIGGER_LABEL_LONG: Record<EscalationTrigger, string> = {
  no_answer: "Respuestas seguidas sin información",
  user_request: "El usuario pide atención humana",
  negative_feedback: "Proporción de valoraciones negativas alta",
  keyword_detected: "Palabra crítica detectada (urgente, denuncia…)",
  confidence_below: "Confianza de búsqueda baja N veces seguidas",
  loop_detected: "Bot repite la misma respuesta",
};

export const TRIGGER_LABEL_SHORT: Record<EscalationTrigger | "manual" | "user_consent", string> = {
  no_answer: "Sin respuesta",
  user_request: "Solicitud del usuario",
  negative_feedback: "Valoración negativa",
  keyword_detected: "Palabra crítica",
  confidence_below: "Confianza baja",
  loop_detected: "Bucle de respuestas",
  manual: "Manual",
  user_consent: "Consentimiento del usuario",
};

export function formatTriggerFallback(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
