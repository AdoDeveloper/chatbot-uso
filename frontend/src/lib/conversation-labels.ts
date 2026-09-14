import type { ConversationStatus } from "@/types";

export const CONVERSATION_STATUS_LABEL: Record<ConversationStatus, string> = {
  active: "Activa",
  escalated: "Sin resolver",
  resolved: "Resuelto",
};
