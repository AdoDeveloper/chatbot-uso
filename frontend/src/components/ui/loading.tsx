"use client";

import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/**
 * Indicador de carga estándar del sistema (estilo skeleton de sección).
 *
 * Se diseñó para reemplazar a la TARJETA COMPLETA durante la carga (no para
 * incrustarse dentro de una Card ya dibujada): muestra un placeholder de
 * encabezado y filas de contenido, de modo que no coexista con el marco
 * vacío de una Card y se perciba claramente como "cargando".
 */
export function Loading({
  title,
  rows = 3,
  className = "",
}: {
  title?: string;
  rows?: number;
  className?: string;
}) {
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={title ? `Cargando ${title}` : "Cargando"}
      className={cn(
        "rounded-xl border border-border bg-card shadow-sm",
        className,
      )}
    >
      <div className="flex items-center justify-between gap-3 border-b border-border px-5 py-4">
        <Skeleton className="h-4 w-44" />
        <Skeleton className="h-4 w-16" />
      </div>
      <div className="space-y-3 p-5">
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} className="h-12 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}

export default Loading;
