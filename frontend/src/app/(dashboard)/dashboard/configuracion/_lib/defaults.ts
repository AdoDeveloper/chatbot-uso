import type { ChatbotSettings } from "@/types";

export const SETTINGS_DEFAULTS: ChatbotSettings = {
 chatbot_name: "Asistente Virtual",
 welcome_message: "¡Hola! ¿En qué puedo ayudarte?",
 system_prompt:
  "Eres un asistente de soporte. Responde únicamente basándote en el siguiente contexto.\n\nCONTEXTO:\n{context}\n\nSi la pregunta no puede responderse con el contexto, indícalo claramente.",
 top_k: 8, score_threshold: 0.30, temperature: 0.3,
 max_tokens: 1024, use_corrective_rag: true, use_reranker: false,
 greeting_response:
  "¡Hola! Soy el asistente virtual de la universidad. ¿En qué puedo ayudarte? Puedo resolver dudas sobre trámites, requisitos, fechas, normativas y más.",
 no_providers_message:
  "En este momento el asistente no está disponible. Por favor, inténtalo más tarde.",
 guardrail_blocked_message:
  "No puedo procesar esa solicitud. ¿Puedo ayudarte con algo sobre la universidad?",
};
