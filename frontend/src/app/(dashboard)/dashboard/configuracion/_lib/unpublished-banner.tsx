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
  // bg-warning sólido (#B45309 + texto blanco): la versión tenue en amber-50
  // se fundía con el fondo claro del dashboard y el aviso pasaba desapercibido.
  <div className="flex items-center gap-2.5 rounded-lg bg-warning px-4 py-2.5 text-sm text-warning-foreground shadow-sm mb-5">
   <AlertTriangle className="w-4 h-4 shrink-0" />
   <span className="flex-1">
    Hay cambios sin publicar. Los usuarios del widget siguen viendo la última versión publicada.
   </span>
   <Link
    href="/dashboard/configuracion/publicaciones"
    className="font-semibold underline underline-offset-2 hover:no-underline shrink-0"
   >
    Publicar ahora
   </Link>
  </div>
 );
}
