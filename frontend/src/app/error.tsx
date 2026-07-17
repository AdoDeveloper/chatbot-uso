"use client";

import { useEffect } from "react";
import { Button } from "@/components/ui/button";
import { AlertCircle } from "lucide-react";
import { apiUrl } from "@/lib/api";

export default function RootError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    if (typeof window !== "undefined") {
      fetch(apiUrl("/health/live"), { method: "HEAD" }).catch(() => {});
    }
  }, [error]);

  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="max-w-sm text-center space-y-4">
        <div className="mx-auto w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center">
          <AlertCircle className="w-6 h-6 text-destructive" />
        </div>
        <h1 className="text-xl font-semibold text-foreground">
          Algo salió mal
        </h1>
        <p className="text-sm text-muted-foreground">
          Ocurrió un error inesperado. Intente de nuevo o vuelva más tarde.
        </p>
        <div className="flex items-center justify-center gap-3">
          <Button onClick={() => reset()}>Intentar de nuevo</Button>
          <Button variant="outline" onClick={() => (window.location.href = "/login")}>
            Volver al inicio
          </Button>
        </div>
      </div>
    </div>
  );
}
