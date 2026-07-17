"use client";

import { useState } from "react";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@/contexts/auth-context";
import { Eye, EyeOff, Bot, AlertCircle, Loader2, KeyRound } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import api from "@/lib/api";
import { getErrorMessage } from "@/hooks/use-api";

const schema = z
  .object({
    current_password: z.string().min(1, "Ingrese su contraseña actual"),
    new_password: z
      .string()
      .min(8, "Mínimo 8 caracteres")
      .regex(/[A-Z]/, "Debe contener al menos una mayúscula")
      .regex(/[0-9]/, "Debe contener al menos un número"),
    confirm_password: z.string().min(1, "Confirme su nueva contraseña"),
  })
  .refine((d) => d.new_password === d.confirm_password, {
    message: "Las contraseñas no coinciden",
    path: ["confirm_password"],
  });

type FormData = z.infer<typeof schema>;

export default function CambiarContrasenaPage() {
  const { refreshUser } = useAuth();
  const [showCurrent, setShowCurrent] = useState(false);
  const [showNew, setShowNew] = useState(false);
  const [serverError, setServerError] = useState("");

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  const onSubmit = async (data: FormData) => {
    setServerError("");
    try {
      await api.post("/auth/change-password", {
        current_password: data.current_password,
        new_password: data.new_password,
      });
      await refreshUser();
    } catch (err: unknown) {
      setServerError(getErrorMessage(err, "No se pudo cambiar la contraseña. Intente de nuevo."));
    }
  };

  return (
    <div className="relative min-h-screen flex flex-col bg-muted/40 overflow-hidden">
      <style>{`
        @keyframes gridMove {
          0%   { background-position: 0 0; }
          100% { background-position: 48px 48px; }
        }
        .login-grid-bg {
          background-image:
            linear-gradient(rgba(15,47,110,0.07) 1px, transparent 1px),
            linear-gradient(90deg, rgba(15,47,110,0.07) 1px, transparent 1px);
          background-size: 48px 48px;
          animation: gridMove 6s linear infinite;
        }
      `}</style>

      <div className="login-grid-bg absolute inset-0 pointer-events-none" />

      <div className="relative flex-1 flex items-center justify-center px-4 py-10">
        <div className="w-full max-w-sm">
          <div className="bg-card rounded-xl shadow-md overflow-hidden border border-border">

            {/* Header */}
            <div className="bg-sidebar px-8 py-6 flex items-center gap-4">
              <div className="flex items-center justify-center w-10 h-10 rounded-lg bg-white/10 shrink-0">
                <Bot className="w-5 h-5 text-white" />
              </div>
              <div className="min-w-0">
                <p className="text-2xs font-semibold uppercase tracking-widest text-white/50 leading-none mb-0.5">
                  Panel de Administración
                </p>
                <p className="text-lg font-bold text-white tracking-tight leading-tight truncate">
                  Chatbot USO
                </p>
              </div>
            </div>

            {/* Body */}
            <div className="px-8 pt-7 pb-5">
              <div className="flex items-center gap-2 mb-1">
                <KeyRound className="w-5 h-5 text-primary" />
                <h1 className="text-xl font-semibold text-foreground">
                  Cambie su contraseña
                </h1>
              </div>
              <p className="text-sm text-muted-foreground mb-6">
                Por seguridad debe establecer una contraseña personal antes de continuar.
              </p>

              {serverError && (
                <Alert variant="destructive" className="mb-5">
                  <AlertCircle className="h-4 w-4" />
                  <AlertDescription>{serverError}</AlertDescription>
                </Alert>
              )}

              <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                {/* Contraseña actual */}
                <div className="space-y-1.5">
                  <Label htmlFor="current_password">Contraseña actual</Label>
                  <div className="relative">
                    <Input
                      id="current_password"
                      type={showCurrent ? "text" : "password"}
                      autoComplete="current-password"
                      className="pr-10"
                      {...register("current_password")}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => setShowCurrent((v) => !v)}
                      aria-label={showCurrent ? "Ocultar" : "Mostrar"}
                      className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 text-muted-foreground"
                    >
                      {showCurrent
                        ? <EyeOff className="w-4 h-4" aria-hidden="true" />
                        : <Eye className="w-4 h-4" aria-hidden="true" />}
                    </Button>
                  </div>
                  {errors.current_password && (
                    <p className="text-xs text-destructive">{errors.current_password.message}</p>
                  )}
                </div>

                {/* Nueva contraseña */}
                <div className="space-y-1.5">
                  <Label htmlFor="new_password">Nueva contraseña</Label>
                  <div className="relative">
                    <Input
                      id="new_password"
                      type={showNew ? "text" : "password"}
                      autoComplete="new-password"
                      className="pr-10"
                      {...register("new_password")}
                    />
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => setShowNew((v) => !v)}
                      aria-label={showNew ? "Ocultar" : "Mostrar"}
                      className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 text-muted-foreground"
                    >
                      {showNew
                        ? <EyeOff className="w-4 h-4" aria-hidden="true" />
                        : <Eye className="w-4 h-4" aria-hidden="true" />}
                    </Button>
                  </div>
                  {errors.new_password && (
                    <p className="text-xs text-destructive">{errors.new_password.message}</p>
                  )}
                </div>

                {/* Confirmar */}
                <div className="space-y-1.5">
                  <Label htmlFor="confirm_password">Confirmar nueva contraseña</Label>
                  <Input
                    id="confirm_password"
                    type="password"
                    autoComplete="new-password"
                    {...register("confirm_password")}
                  />
                  {errors.confirm_password && (
                    <p className="text-xs text-destructive">{errors.confirm_password.message}</p>
                  )}
                </div>

                <Button type="submit" disabled={isSubmitting} className="w-full mt-1">
                  {isSubmitting
                    ? <><Loader2 className="h-4 w-4 animate-spin mr-2" />Guardando...</>
                    : "Establecer contraseña"}
                </Button>
              </form>
            </div>

            <div className="px-8 py-3 border-t border-border/60 text-center text-2xs text-muted-foreground">
              © {new Date().getFullYear()} Universidad de Sonsonate
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
