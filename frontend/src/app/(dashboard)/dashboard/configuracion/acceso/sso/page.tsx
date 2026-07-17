"use client";

import { useEffect, useState } from "react";
import api from "@/lib/api";
import { useApi, getErrorMessage } from "@/hooks/use-api";
import { usePermission } from "@/hooks/use-permission";
import { PERM } from "@/lib/permissions";
import { useToast } from "@/components/ui/toast";
import { Lock, Copy, CheckCircle, XCircle, AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Skeleton } from "@/components/ui/skeleton";

function MicrosoftLogo({ className }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 21 21" xmlns="http://www.w3.org/2000/svg">
      <rect x="1"  y="1"  width="9" height="9" fill="#f25022" />
      <rect x="11" y="1"  width="9" height="9" fill="#7fba00" />
      <rect x="1"  y="11" width="9" height="9" fill="#00a4ef" />
      <rect x="11" y="11" width="9" height="9" fill="#ffb900" />
    </svg>
  );
}

interface AuthMethodsOut {
  credentials_enabled: boolean;
}

interface OAuthConfigOut {
  provider: string;
  has_client_id: boolean;
  has_client_secret: boolean;
  tenant_id: string;
  allowed_domains: string[];
  is_active: boolean;
  configured: boolean;
}

export default function SsoPage() {
  const can = usePermission();
  const { toast } = useToast();
  const canManage = can(PERM.SYSTEM_MANAGE);

  const [credEnabled, setCredEnabled] = useState(true);
  const [savingCred, setSavingCred] = useState(false);

  const { data: methodsData, loading: loadingMethods } = useApi<AuthMethodsOut>("/integrations/auth-methods");
  const { data: oauthData, loading: loadingOauth } = useApi<OAuthConfigOut>("/integrations/oauth");
  const loading = loadingMethods || loadingOauth;

  const [oauth, setOauth] = useState<OAuthConfigOut | null>(null);
  const [msActive, setMsActive] = useState(false);
  const [allowedDomains, setAllowedDomains] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (methodsData) setCredEnabled(methodsData.credentials_enabled);
  }, [methodsData]);

  useEffect(() => {
    if (!oauthData) return;
    setOauth(oauthData);
    setMsActive(oauthData.is_active);
    setAllowedDomains(oauthData.allowed_domains.join(", "));
  }, [oauthData]);

  const domainsDirty = !!oauth && allowedDomains !== oauth.allowed_domains.join(", ");

  async function saveCredentials(enabled: boolean) {
    if (!enabled && !oauth?.is_active) {
      toast({ type: "warning", title: "Acción no permitida", message: "Activa Microsoft SSO antes de deshabilitar el inicio de sesión con contraseña." });
      return;
    }
    setSavingCred(true);
    try {
      await api.put("/integrations/auth-methods", { credentials_enabled: enabled });
      setCredEnabled(enabled);
      toast({ message: `Inicio con contraseña ${enabled ? "activado" : "desactivado"}.`, type: "success" });
    } catch (err) {
      toast({ message: getErrorMessage(err, "Error al guardar la configuración."), type: "error" });
    } finally {
      setSavingCred(false);
    }
  }

  async function toggleMicrosoft(next: boolean) {
    if (!next && !credEnabled) {
      toast({ type: "warning", title: "Acción no permitida", message: "Activa el inicio de sesión con contraseña antes de desactivar Microsoft SSO." });
      return;
    }
    if (next && !oauth?.configured) {
      toast({ type: "warning", title: "Credenciales no configuradas", message: "Las credenciales de Microsoft no están configuradas en el servidor." });
      return;
    }
    if (domainsDirty) {
      toast({ type: "warning", title: "Cambios sin guardar", message: "Guarde los dominios permitidos antes de activar o desactivar Microsoft SSO." });
      return;
    }
    setSaving(true);
    try {
      const { data } = await api.put<OAuthConfigOut>("/integrations/oauth", {
        allowed_domains: oauth?.allowed_domains ?? [],
        is_active: next,
      });
      setOauth(data);
      setMsActive(data.is_active);
      toast({ message: `Microsoft SSO ${next ? "activado" : "desactivado"}.`, type: "success" });
    } catch (err) {
      toast({ message: getErrorMessage(err, "No se pudo guardar la configuración."), type: "error" });
    } finally {
      setSaving(false);
    }
  }

  async function saveDomains() {
    setSaving(true);
    try {
      const domains = allowedDomains.split(",").map((d) => d.trim()).filter(Boolean);
      const { data } = await api.put<OAuthConfigOut>("/integrations/oauth", {
        allowed_domains: domains,
        is_active: oauth?.is_active ?? false,
      });
      setOauth(data);
      setAllowedDomains(data.allowed_domains.join(", "));
      toast({ message: "Dominios permitidos guardados.", type: "success" });
    } catch (err) {
      toast({ message: getErrorMessage(err, "No se pudo guardar la configuración."), type: "error" });
    } finally {
      setSaving(false);
    }
  }

  function copyRedirectUri() {
    if (typeof window === "undefined") return;
    const uri = `${window.location.origin}/api/auth/callback/microsoft`;
    navigator.clipboard.writeText(uri);
    toast({ message: "URL copiada al portapapeles.", type: "success" });
  }

  return (
    <div className="space-y-4">

      {/* Credentials */}
      {loadingMethods ? (
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-56" />
            <Skeleton className="h-3 w-72 mt-2" />
          </CardHeader>
          <CardContent>
            <div className="flex items-center justify-between">
              <Skeleton className="h-5 w-28" />
              <Skeleton className="h-6 w-11 rounded-full" />
            </div>
          </CardContent>
        </Card>
      ) : (
      <Card>
        <CardHeader>
          <CardTitle className="text-15 font-semibold flex items-center gap-1.5">
            <Lock className="w-4 h-4" /> Inicio de sesión con contraseña
          </CardTitle>
          <CardDescription className="text-2xs">
            Permite iniciar sesión con correo y contraseña del sistema.{" "}
            <span className="italic">El cambio se aplica al instante.</span>
          </CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {credEnabled
                ? <CheckCircle className="w-4 h-4 text-success" />
                : <XCircle className="w-4 h-4 text-muted-foreground" />}
              <span className="text-13">{credEnabled ? "Habilitado" : "Deshabilitado"}</span>
            </div>
            <Switch checked={credEnabled} onCheckedChange={saveCredentials} disabled={savingCred || !canManage} />
          </div>
        </CardContent>
      </Card>
      )}

      {/* Microsoft SSO */}
      {loadingOauth ? (
        <Card>
          <CardHeader>
            <Skeleton className="h-5 w-56" />
            <Skeleton className="h-3 w-72 mt-2" />
          </CardHeader>
          <CardContent className="space-y-4">
            <Skeleton className="h-16 w-full rounded-lg" />
            <div className="flex items-center justify-between">
              <div className="space-y-1.5">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-56" />
              </div>
              <Skeleton className="h-6 w-11 rounded-full" />
            </div>
            <Skeleton className="h-9 w-full" />
            <Skeleton className="h-9 w-full" />
          </CardContent>
        </Card>
      ) : (
      <Card>
        <CardHeader>
          <CardTitle className="text-15 font-semibold flex items-center gap-1.5">
            <MicrosoftLogo className="w-4 h-4" /> Microsoft SSO (Azure AD)
          </CardTitle>
          <CardDescription className="text-2xs">
            Inicio de sesión con cuentas corporativas de Microsoft 365.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-4">

          {/* Credential status — read-only, comes from .env */}
          <div className="rounded-lg border border-border bg-muted/30 p-3 space-y-1.5">
            <p className="text-2xs font-medium text-muted-foreground">Estado de credenciales del servidor</p>
            <div className="flex flex-wrap gap-3">
              <span className="flex items-center gap-1.5 text-2xs">
                {oauth?.has_client_id
                  ? <CheckCircle className="w-3.5 h-3.5 text-success" />
                  : <XCircle className="w-3.5 h-3.5 text-destructive" />}
                Client ID
              </span>
              <span className="flex items-center gap-1.5 text-xs">
                {oauth?.has_client_secret
                  ? <CheckCircle className="w-3.5 h-3.5 text-success" />
                  : <XCircle className="w-3.5 h-3.5 text-destructive" />}
                Client Secret
              </span>
              <span className="flex items-center gap-1.5 text-xs">
                {oauth?.tenant_id
                  ? <CheckCircle className="w-3.5 h-3.5 text-success" />
                  : <XCircle className="w-3.5 h-3.5 text-destructive" />}
                Tenant ID{oauth?.tenant_id ? <span className="font-mono text-muted-foreground">{oauth.tenant_id.slice(0, 8)}…</span> : null}
              </span>
            </div>
            {!oauth?.configured && (
              <p className="text-2xs text-warning flex items-center gap-1 mt-1">
                <AlertTriangle className="w-3 h-3 shrink-0" />
                Las credenciales se configuran en el servidor.
              </p>
            )}
          </div>

          {/* Active toggle */}
          <div className="flex items-center justify-between">
            <div>
              <p className="text-13 font-medium">Activar Microsoft SSO</p>
              <p className="text-2xs text-muted-foreground mt-0.5">
                {oauth?.configured
                  ? "Permite iniciar sesión con cuentas de Microsoft."
                  : "Requiere que las credenciales estén configuradas en el servidor."}
              </p>
            </div>
            <Switch
              checked={msActive}
              onCheckedChange={toggleMicrosoft}
              disabled={saving || !canManage || !oauth?.configured || domainsDirty}
            />
          </div>

          {/* Allowed domains */}
          <div className="space-y-1">
            <label className="block text-2xs font-medium text-foreground">
              Dominios permitidos <span className="font-normal text-muted-foreground">(opcional, separados por coma)</span>
            </label>
            <Input
              value={allowedDomains}
              onChange={(e) => setAllowedDomains(e.target.value)}
              placeholder="empresa.com, filial.com — vacío = cualquier cuenta Microsoft"
              disabled={!canManage}
            />
            <p className="text-2xs text-muted-foreground">Si se define, solo se aceptarán cuentas de esos dominios.</p>
          </div>

          {canManage && (
            <div className="flex items-center justify-end gap-3">
              {domainsDirty && !saving && (
                <span className="text-2xs text-muted-foreground">Cambios sin guardar</span>
              )}
              <Button size="sm" onClick={saveDomains} disabled={saving || !domainsDirty}>
                {saving ? "Guardando..." : "Guardar"}
              </Button>
            </div>
          )}

          {/* Redirect URI (read-only, for Azure app registration) */}
          <div className="space-y-1">
            <label className="block text-2xs font-medium text-muted-foreground">
              Redirect URI <span className="font-normal">(copie esta URL en su app de Azure)</span>
            </label>
            <div className="flex gap-2">
              <Input
                value={typeof window !== "undefined" ? `${window.location.origin}/api/auth/callback/microsoft` : ""}
                readOnly
                className="font-mono text-xs bg-muted/40"
              />
              <Button variant="outline" size="sm" onClick={copyRedirectUri}>
                <Copy className="w-3.5 h-3.5" />
              </Button>
            </div>
          </div>

          {!credEnabled && !oauth?.is_active && (
            <div className="flex items-center gap-2 text-warning text-xs bg-warning/5 border border-warning/30 rounded-lg p-2.5">
              <AlertTriangle className="w-3.5 h-3.5 shrink-0" />
              Ambos métodos están desactivados. Los usuarios no podrán iniciar sesión.
            </div>
          )}
        </CardContent>
      </Card>
      )}
    </div>
  );
}
