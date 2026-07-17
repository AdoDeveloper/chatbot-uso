"use client";

import { Button } from "@/components/ui/button";
import { AlertCircle } from "lucide-react";

export default function AuthError({
  error: _error,
  reset: _reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background p-4">
      <div className="max-w-sm text-center space-y-4">
        <div className="mx-auto w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center">
          <AlertCircle className="w-6 h-6 text-destructive" />
        </div>
        <h1 className="text-xl font-semibold text-foreground">
          Error de autenticación
        </h1>
        <p className="text-sm text-muted-foreground">
          Hubo un problema al cargar esta página. Intenta acceder de nuevo.
        </p>
        <Button onClick={() => (window.location.href = "/login")}>
          Volver al inicio de sesión
        </Button>
      </div>
    </div>
  );
}
