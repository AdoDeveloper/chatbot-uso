import type { EscalationTrigger } from "@/types";

export const TRIGGER_LABEL_LONG: Record<EscalationTrigger, string> = {
  no_answer: "Sin respuesta tras N segundos",
  user_request: "Usuario solicita hablar con agente",
  negative_feedback: "Proporción de valoraciones negativas alta",
  keyword_detected: "Palabra crítica detectada (urgente, denuncia…)",
  confidence_below: "Confianza RAG baja N veces seguidas",
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
  // Emitido por app/services/widget/service.py - el usuario acepta hablar
  // con un humano desde el widget, sin pasar por un trigger automático.
  user_consent: "Consentimiento del usuario",
};

// Último recurso para cualquier trigger nuevo que el backend agregue sin
// actualizar este diccionario: nunca mostrar el snake_case crudo.
export function formatTriggerFallback(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
