"use client";

import { useEffect, useState } from "react";
import { useParams, useRouter } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import api, { tokenStore } from "@/lib/api";
import { getErrorMessage } from "@/hooks/use-api";
import type { TokenResponse } from "@/types";
import { Bot, Eye, EyeOff, ShieldCheck, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { formatInProjectTz } from "@/lib/datetime";

interface InviteInfo {
  email: string;
  role: string;
  expires_at: string;
  is_usable: boolean;
}

const schema = z
  .object({
    full_name: z.string().min(2, { message: "El nombre debe tener al menos 2 caracteres" }),
    password: z.string().min(8, { message: "La contraseña debe tener al menos 8 caracteres" }),
    confirm_password: z.string(),
  })
  .refine((d) => d.password === d.confirm_password, {
    message: "Las contraseñas no coinciden",
    path: ["confirm_password"],
  });

type FormData = z.infer<typeof schema>;

const ROLE_LABEL: Record<string, string> = {
  admin:  "Administrador",
  editor: "Editor",
  viewer: "Lector",
};

const ROLE_COLOR: Record<string, string> = {
  admin:  "bg-primary/10 text-primary",
  editor: "bg-brand-green/10 text-brand-green",
  viewer: "bg-muted text-muted-foreground",
};

export default function InvitePage() {
  const { token } = useParams<{ token: string }>();
  const router = useRouter();

  const [info, setInfo] = useState<InviteInfo | null>(null);
  const [loadingInfo, setLoadingInfo] = useState(true);
  const [infoError, setInfoError] = useState<string | null>(null);
  const [showPassword, setShowPassword] = useState(false);
  const [showConfirm, setShowConfirm] = useState(false);
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  useEffect(() => {
    if (!token) return;
    api
      .get<InviteInfo>(`/auth/invite/${token}`)
      .then(({ data }) => setInfo(data))
      .catch((err: unknown) => {
        setInfoError(getErrorMessage(err, "Invitación no válida"));
      })
      .finally(() => setLoadingInfo(false));
  }, [token]);

  const onSubmit = async (values: FormData) => {
    setServerError(null);
    try {
      const { data } = await api.post<TokenResponse>(`/auth/invite/${token}/accept`, {
        full_name: values.full_name,
        password: values.password,
      });
      tokenStore.set(data.access_token, data.refresh_token);
      router.push("/dashboard");
    } catch (err: unknown) {
      setServerError(getErrorMessage(err, "No se pudo completar el registro"));
    }
  };

  if (loadingInfo) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <span className="text-muted-foreground text-sm">Verificando invitación...</span>
      </div>
    );
  }

  if (infoError || !info) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4">
        <div className="bg-card rounded-2xl shadow-sm border border-border p-8 max-w-md w-full text-center space-y-4">
          <div className="w-14 h-14 rounded-2xl bg-destructive/10 flex items-center justify-center mx-auto">
            <AlertTriangle className="w-7 h-7 text-destructive" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">Invitación no válida</h1>
            <p className="text-sm text-muted-foreground mt-1">{infoError}</p>
          </div>
          <Button
            variant="link"
            onClick={() => router.push("/login")}
            className="text-sm"
          >
            Ir al inicio de sesión
          </Button>
        </div>
      </div>
    );
  }

  if (!info.is_usable) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background px-4">
        <div className="bg-card rounded-2xl shadow-sm border border-border p-8 max-w-md w-full text-center space-y-4">
          <div className="w-14 h-14 rounded-2xl flex items-center justify-center mx-auto">
            <AlertTriangle className="w-7 h-7 text-warning" />
          </div>
          <div>
            <h1 className="text-xl font-bold text-foreground">Invitación expirada</h1>
            <p className="text-sm text-muted-foreground mt-1">
              Este enlace ya fue utilizado, expiró o fue revocado.
            </p>
            <p className="text-sm text-muted-foreground mt-1">
              Solicita una nueva invitación.
            </p>
          </div>
          <Button
            variant="link"
            onClick={() => router.push("/login")}
            className="text-sm"
          >
            Ir al inicio de sesión
          </Button>
        </div>
      </div>
    );
  }

  return (
    <div className="min-h-screen flex items-center justify-center bg-background px-4">
      <div className="bg-card rounded-2xl shadow-sm border border-border p-8 max-w-md w-full space-y-6">
        {/* Header */}
        <div className="text-center space-y-3">
          <div className="w-14 h-14 rounded-2xl bg-primary/10 flex items-center justify-center mx-auto">
            <Bot className="w-7 h-7 text-primary" />
          </div>
          <div>
            <h1 className="text-2xl font-bold text-foreground">Crear cuenta</h1>
            <p className="text-sm text-muted-foreground mt-1">Complete su registro para acceder al panel</p>
          </div>
        </div>

        {/* Invite info */}
        <div className="bg-muted/50 rounded-xl p-4 space-y-2">
          <div className="flex items-center gap-2">
            <ShieldCheck className="w-4 h-4 text-primary shrink-0" />
            <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
              Invitación para
            </span>
          </div>
          <p className="text-sm font-medium text-foreground">{info.email}</p>
          <div className="flex items-center gap-2">
            <span className={`text-xs px-2.5 py-1 rounded-full font-medium ${ROLE_COLOR[info.role] ?? "bg-muted text-muted-foreground"}`}>
              {ROLE_LABEL[info.role] ?? info.role}
            </span>
            <span className="text-xs text-muted-foreground">
              Expira{" "}
              {formatInProjectTz(info.expires_at, {
                day: "2-digit",
                month: "short",
                year: "numeric",
              })}
            </span>
          </div>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          {serverError && (
            <Alert variant="destructive">
              <AlertDescription>{serverError}</AlertDescription>
            </Alert>
          )}

          <div className="space-y-1.5">
            <Label htmlFor="invite-name">Nombre completo</Label>
            <Input
              id="invite-name"
              {...register("full_name")}
              type="text"
              autoComplete="name"
              placeholder="Su nombre completo"
            />
            {errors.full_name && (
              <p className="text-xs text-destructive">{errors.full_name.message}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="invite-pass">Contraseña</Label>
            <div className="relative">
              <Input
                id="invite-pass"
                {...register("password")}
                type={showPassword ? "text" : "password"}
                autoComplete="new-password"
                placeholder="Mínimo 8 caracteres"
                className="pr-10"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setShowPassword((p) => !p)}
                aria-label={showPassword ? "Ocultar contraseña" : "Mostrar contraseña"}
                className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 text-muted-foreground"
              >
                {showPassword ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </Button>
            </div>
            {errors.password && (
              <p className="text-xs text-destructive">{errors.password.message}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="invite-confirm">Confirmar contraseña</Label>
            <div className="relative">
              <Input
                id="invite-confirm"
                {...register("confirm_password")}
                type={showConfirm ? "text" : "password"}
                autoComplete="new-password"
                placeholder="Repite la contraseña"
                className="pr-10"
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => setShowConfirm((p) => !p)}
                aria-label={showConfirm ? "Ocultar contraseña" : "Mostrar contraseña"}
                className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 text-muted-foreground"
              >
                {showConfirm ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
              </Button>
            </div>
            {errors.confirm_password && (
              <p className="text-xs text-destructive">{errors.confirm_password.message}</p>
            )}
          </div>

          <Button type="submit" disabled={isSubmitting} className="w-full">
            {isSubmitting ? "Creando cuenta..." : "Crear cuenta y acceder"}
          </Button>
        </form>

        <p className="text-center text-xs text-muted-foreground">
          ¿Ya tiene cuenta?{" "}
          <a href="/login" className="text-primary hover:underline">
            Iniciar sesión
          </a>
        </p>
      </div>
    </div>
  );
}
