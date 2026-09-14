import { FileText, AlertCircle, UserRound, Plug, Inbox, type LucideIcon } from "lucide-react";

export const EVENT_META: Record<string, { label: string; icon: LucideIcon; href?: string }> = {
  doc_ready: { label: "Documento procesado", icon: FileText, href: "/dashboard/conocimiento/documentos" },
  doc_error: { label: "Error procesando documento", icon: AlertCircle, href: "/dashboard/conocimiento/documentos" },
  escalation: { label: "Chat escalado a humano", icon: UserRound, href: "/dashboard/conversaciones?status=escalated" },
  provider_down: { label: "Proveedor IA caído", icon: Plug, href: "/dashboard/configuracion/proveedores" },
  provider_degraded: { label: "Proveedor IA degradado", icon: Plug, href: "/dashboard/configuracion/proveedores" },
  provider_misconfigured: { label: "Proveedor IA mal configurado", icon: Plug, href: "/dashboard/configuracion/proveedores" },
  service_down: { label: "Servicio degradado", icon: Plug, href: "/dashboard/configuracion/proveedores" },
  rate_limit_threshold: { label: "Cerca del límite de cuotas", icon: AlertCircle, href: "/dashboard/configuracion/estado/cuotas/limites" },
  unanswered_digest: { label: "Resumen diario", icon: Inbox, href: "/dashboard/conversaciones/pendientes" },
};

export function formatEventFallback(value: string): string {
  return value.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
