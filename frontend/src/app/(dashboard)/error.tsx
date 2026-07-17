"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { AlertCircle } from "lucide-react";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // eslint-disable-next-line no-console
    console.error("[dashboard.error_boundary]", error);
  }, [error]);

  return (
    <div className="flex flex-col items-center justify-center py-16 text-center">
      <div className="mx-auto w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center mb-4">
        <AlertCircle className="w-6 h-6 text-destructive" />
      </div>
      <h2 className="text-lg font-semibold text-foreground mb-1">
        Error en esta sección
      </h2>
      <p className="text-13 text-muted-foreground max-w-xs mb-5">
        No se pudo cargar esta página. Probablemente sea un problema temporal.
      </p>
      <div className="flex items-center gap-3">
        <Button onClick={() => reset()}>Reintentar</Button>
        <Button variant="outline" onClick={() => (window.location.href = "/dashboard")}>
          Ir al inicio
        </Button>
      </div>
    </div>
  );
}
