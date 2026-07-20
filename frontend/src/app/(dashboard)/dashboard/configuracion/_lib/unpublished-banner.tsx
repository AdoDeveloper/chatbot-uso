"use client";

import Link from "next/link";
import { AlertTriangle } from "lucide-react";
import { useApi } from "@/hooks/use-api";

export function UnpublishedBanner() {
 const { data } = useApi<{ config_changed_since_deploy: boolean; never_deployed: boolean }>(
  "/versions/deploy/status"
 );
 const show = data ? (data.never_deployed || data.config_changed_since_deploy) : false;

 if (!show) return null;

 return (
  // Mismo patrón que el resto de avisos de warning del sistema (ver
  // estadisticas/page.tsx): fondo tenue + acento de borde izquierdo, texto
  // en text-foreground (no text-warning-foreground, pensado para fondo
  // sólido — sobre bg-warning/10 quedaría casi blanco sobre casi blanco).
  <div className="flex items-center gap-2.5 rounded-lg border-l-4 border-warning bg-warning/10 px-4 py-2.5 text-sm shadow-sm mb-5">
   <AlertTriangle className="w-4 h-4 shrink-0 text-warning" />
   <span className="flex-1 text-foreground">
    Hay cambios sin publicar. Los usuarios del widget siguen viendo la última versión publicada.
   </span>
   <Link
    href="/dashboard/configuracion/publicaciones"
    className="font-semibold text-warning underline underline-offset-2 hover:no-underline shrink-0"
   >
    Publicar ahora
   </Link>
  </div>
 );
}
