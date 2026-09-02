import type { EscalationTrigger } from "@/types";

export const TRIGGER_LABEL_LONG: Record<EscalationTrigger, string> = {
  no_answer: "Sin respuesta tras N segundos",
  user_request: "Usuario solicita hablar con agente",
  negative_feedback: "Proporción de valoraciones negativas alta",
  keyword_detected: "Palabra crítica detectada (urgente, denuncia…)",
  confidence_below: "Confianza RAG baja N veces seguidas",
  loop_detected: "Bot repite la misma respuesta",
};

export const TRIGGER_LABEL_SHORT: Record<EscalationTrigger | "manual", string> = {
  no_answer: "Sin respuesta",
  user_request: "Solicitud del usuario",
  negative_feedback: "Valoración negativa",
  keyword_detected: "Palabra crítica",
  confidence_below: "Confianza baja",
  loop_detected: "Bucle de respuestas",
  manual: "Manual",
};
