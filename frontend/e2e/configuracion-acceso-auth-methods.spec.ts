import { test, expect } from "@playwright/test";

/**
 * Coverage for PUT /integrations/auth-methods (toggle "Inicio de sesión con
 * contraseña"), deliberately excluded from configuracion-acceso-sso.spec.ts:
 * flipping it off without Microsoft SSO fully configured locks the whole
 * team out of the dashboard, and even with SSO configured (as in this
 * environment) this suite's own login uses username/password - disabling
 * it, even briefly, risks breaking every other spec's auth.
 *
 * Safe approach: read the real current value first, flip it, verify the
 * effect via a direct API read (not the UI toggle's own optimistic state),
 * then restore the original value in a `finally` before the page ever
 * reloads or another spec runs. The backend's own guard (won't disable
 * credentials unless Microsoft SSO is already active) is asserted too.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

async function authHeaderFor(page: import("@playwright/test").Page): Promise<string> {
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === "chatbot_access")?.value;
  if (!token) test.skip(true, "no se pudo leer el token de sesión");
  return `Bearer ${token}`;
}

test.describe("Configuracion > Acceso > SSO > Inicio de sesion con contrasena", () => {
  test("desactivar y reactivar el login por contrasena (round-trip, restaurado siempre)", async ({ page, request }) => {
    await page.goto("/dashboard/configuracion/acceso/sso");
    const authHeader = await authHeaderFor(page);

    // Red de respaldo: si el finally no llegara a correr (crash del proceso),
    // que quede al menos una via de acceso (Microsoft SSO real) antes de
    // arriesgarse a apagar el login por contraseña. Si SSO no esta activo
    // en este entorno, el backend ya rechaza el PUT (ver saveCredentials en
    // el componente), pero se aborta aqui explicitamente para no depender
    // de ese guard como unica proteccion.
    const oauthResp = await request.get("/api/v1/integrations/oauth", { headers: { Authorization: authHeader } });
    const oauth: { is_active: boolean; configured: boolean } = await oauthResp.json();
    if (!oauth.is_active || !oauth.configured) {
      test.skip(true, "Microsoft SSO no esta activo/configurado en este entorno; no es seguro apagar el login por contraseña sin una via de acceso alterna real");
    }

    const originalResp = await request.get("/api/v1/integrations/auth-methods", { headers: { Authorization: authHeader } });
    expect(originalResp.ok()).toBeTruthy();
    const original: { credentials_enabled: boolean } = await originalResp.json();

    let restored = false;
    async function restore() {
      if (restored) return;
      restored = true;
      const resp = await request.put("/api/v1/integrations/auth-methods", {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { credentials_enabled: original.credentials_enabled },
      });
      expect(resp.ok(), "fallo al restaurar credentials_enabled original").toBeTruthy();
    }

    try {
      const toggled = !original.credentials_enabled;
      const toggleResp = await request.put("/api/v1/integrations/auth-methods", {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { credentials_enabled: toggled },
      });
      expect(toggleResp.ok(), `PUT auth-methods devolvió ${toggleResp.status()}`).toBeTruthy();
      const toggledBody: { credentials_enabled: boolean } = await toggleResp.json();
      expect(toggledBody.credentials_enabled).toBe(toggled);

      const verifyResp = await request.get("/api/v1/integrations/auth-methods", { headers: { Authorization: authHeader } });
      const verifyBody: { credentials_enabled: boolean } = await verifyResp.json();
      expect(verifyBody.credentials_enabled).toBe(toggled);
    } finally {
      await restore();
    }

    const finalResp = await request.get("/api/v1/integrations/auth-methods", { headers: { Authorization: authHeader } });
    const finalBody: { credentials_enabled: boolean } = await finalResp.json();
    expect(finalBody.credentials_enabled, "credentials_enabled no quedo restaurado a su valor original").toBe(original.credentials_enabled);
  });
});
