"use client";

import { useEffect, useState, Suspense } from "react";
import { useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { useAuth } from "@/contexts/auth-context";
import { Eye, EyeOff, AlertCircle, Loader2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { APP_URL } from "@/lib/config";
import api from "@/lib/api";
import { getErrorMessage } from "@/hooks/use-api";

interface AuthProviders {
  credentials: boolean;
  microsoft: boolean;
  microsoft_client_id: string | null;
  microsoft_tenant_id: string | null;
}

const schema = z.object({
  email: z.string().email({ message: "Correo inválido" }),
  password: z.string().min(1, { message: "Ingrese su contraseña" }),
});

type FormData = z.infer<typeof schema>;

export default function LoginPage() {
  return (
    <Suspense>
      <LoginContent />
    </Suspense>
  );
}

function LoginContent() {
  const { login } = useAuth();
  const searchParams = useSearchParams();

  const [providers, setProviders] = useState<AuthProviders | null>(null);
  const [providersLoading, setProvidersLoading] = useState(true);
  const [showPass, setShowPass] = useState(false);
  const [serverError, setServerError] = useState(
    searchParams.get("error") ?? ""
  );

  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(schema) });

  useEffect(() => {
    api
      .get<AuthProviders>("/auth/providers")
      .then(({ data }) => setProviders(data))
      .catch(() =>
        setProviders({ credentials: true, microsoft: false, microsoft_client_id: null, microsoft_tenant_id: null })
      )
      .finally(() => setProvidersLoading(false));
  }, []);

  const onSubmit = async (data: FormData) => {
    setServerError("");
    try {
      await login(data.email, data.password);
    } catch (err: unknown) {
      setServerError(getErrorMessage(err, "Correo o contraseña incorrectos"));
    }
  };

  const handleMicrosoft = () => {
    if (!providers?.microsoft_client_id || !providers.microsoft_tenant_id) return;
    const redirectUri = `${APP_URL}/api/auth/callback/microsoft`;
    // state previene ataques CSRF (RFC 6749 §10.12): se guarda en cookie httpOnly-like para que
    // el callback server-side pueda leerla y comparar con lo que devuelve Microsoft.
    const state = crypto.randomUUID();
    const secure = window.location.protocol === "https:" ? "; Secure" : "";
    document.cookie = `oauth_state=${state}; path=/; max-age=600; SameSite=Lax${secure}`;
    const params = new URLSearchParams({
      client_id: providers.microsoft_client_id,
      response_type: "code",
      redirect_uri: redirectUri,
      scope: "openid email profile",
      response_mode: "query",
      prompt: "select_account",
      state,
    });
    window.location.href =
      `https://login.microsoftonline.com/${providers.microsoft_tenant_id}/oauth2/v2.0/authorize?${params}`;
  };

  const showBoth = providers?.credentials && providers?.microsoft;

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

      {/* Animated grid overlay */}
      <div className="login-grid-bg absolute inset-0 pointer-events-none" />

      {/* Main content */}
      <div className="relative flex-1 flex items-center justify-center px-4 py-10">
      <div className="w-full max-w-sm">

        {/* Card */}
        <div className="bg-card rounded-xl shadow-md overflow-hidden border border-border">

          {/* Brand header */}
          <div className="bg-sidebar px-8 py-6 flex flex-col items-center text-center gap-2">
            <img src="/logo_uso.png" alt="Universidad de Sonsonate" className="w-full max-w-[180px] h-auto object-contain" />
            <div>
              <p className="text-2xs font-semibold uppercase tracking-widest text-white/50 leading-none mb-1">
                Panel de Administración
              </p>
              <p className="text-lg font-bold text-white tracking-tight leading-tight">
                Chatbot USO
              </p>
            </div>
          </div>

          {/* Body */}
          <div className="px-8 pt-7 pb-5">
            <h1 className="text-xl font-semibold text-foreground mb-6">
              Acceder
            </h1>

            {serverError && (
              <Alert variant="destructive" className="mb-5">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>{serverError}</AlertDescription>
              </Alert>
            )}

            {/* Loading skeleton */}
            {providersLoading && (
              <div className="flex justify-center py-8">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            )}

            {!providersLoading && providers && (
              <div className="space-y-4">

                {/* Credentials form */}
                {providers.credentials && (
                  <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
                    <div className="space-y-1.5">
                      <Label htmlFor="login-email">Correo electrónico</Label>
                      <Input
                        id="login-email"
                        type="email"
                        autoComplete="email"
                        placeholder="usuario@ejemplo.com"
                        {...register("email")}
                      />
                      {errors.email && (
                        <p className="text-xs text-destructive">{errors.email.message}</p>
                      )}
                    </div>

                    <div className="space-y-1.5">
                      <Label htmlFor="login-password">Contraseña</Label>
                      <div className="relative">
                        <Input
                          id="login-password"
                          type={showPass ? "text" : "password"}
                          autoComplete="current-password"
                          className="pr-10"
                          {...register("password")}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={() => setShowPass((v) => !v)}
                          aria-label={showPass ? "Ocultar contraseña" : "Mostrar contraseña"}
                          className="absolute right-1 top-1/2 -translate-y-1/2 h-7 w-7 text-muted-foreground"
                        >
                          {showPass
                            ? <EyeOff className="w-4 h-4" aria-hidden="true" />
                            : <Eye className="w-4 h-4" aria-hidden="true" />}
                        </Button>
                      </div>
                      {errors.password && (
                        <p className="text-xs text-destructive">{errors.password.message}</p>
                      )}
                    </div>

                    <Button type="submit" disabled={isSubmitting} className="w-full mt-1">
                      {isSubmitting
                        ? <><Loader2 className="h-4 w-4 animate-spin mr-2" />Iniciando sesión...</>
                        : "Acceder"}
                    </Button>
                  </form>
                )}

                {/* Divider */}
                {showBoth && (
                  <div className="relative">
                    <div className="absolute inset-0 flex items-center">
                      <div className="w-full border-t border-border" />
                    </div>
                    <div className="relative flex justify-center text-xs">
                      <span className="bg-card px-3 text-muted-foreground">
                        o identifíquese usando su cuenta en
                      </span>
                    </div>
                  </div>
                )}

                {/* Microsoft SSO */}
                {providers.microsoft && (
                  <Button
                    type="button"
                    variant="outline"
                    className="w-full gap-3"
                    onClick={handleMicrosoft}
                  >
                    <MicrosoftLogo />
                    Microsoft
                  </Button>
                )}

              </div>
            )}
          </div>

          {/* Footer dentro de la card */}
          <div className="px-8 py-3 border-t border-border/60 text-center text-2xs text-muted-foreground">
            © {new Date().getFullYear()} Universidad de Sonsonate
          </div>
        </div>

      </div>
      </div>
    </div>
  );
}

function MicrosoftLogo() {
  return (
    <svg width="16" height="16" viewBox="0 0 21 21" aria-hidden="true">
      <rect x="0"  y="0"  width="10" height="10" fill="#F25022" />
      <rect x="11" y="0"  width="10" height="10" fill="#7FBA00" />
      <rect x="0"  y="11" width="10" height="10" fill="#00A4EF" />
      <rect x="11" y="11" width="10" height="10" fill="#FFB900" />
    </svg>
  );
}
