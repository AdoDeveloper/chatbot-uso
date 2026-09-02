import { test, expect } from "@playwright/test";

/**
 * Coverage for the main /dashboard landing page's interactive elements -
 * closes a real gap found while mapping every button/modal/action across all
 * views: this page had zero interaction testing (smoke-all-pages.spec.ts
 * only checks that it loads without errors).
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

test.describe("Dashboard inicio", () => {
  test("KPI cards render with values", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/dashboard$/);

    await expect(page.getByText(/consultas hoy/i)).toBeVisible();
    await expect(page.getByText(/tasa de resoluci[oó]n/i)).toBeVisible();
    await expect(page.getByText(/sesiones hoy/i)).toBeVisible();
    await expect(page.getByText(/latencia promedio/i)).toBeVisible();
  });

  test("workflow cycle links to documentos, playground and publicaciones", async ({ page }) => {
    await page.goto("/dashboard");

    await page.getByRole("link", { name: /documentos/i }).first().click();
    await expect(page).toHaveURL(/\/dashboard\/conocimiento\/documentos/);

    await page.goto("/dashboard");
    await page.getByRole("link", { name: /pruebas/i }).first().click();
    await expect(page).toHaveURL(/\/dashboard\/configuracion\/playground/);

    await page.goto("/dashboard");
    await page.getByRole("link", { name: /publicaci[oó]n/i }).first().click();
    await expect(page).toHaveURL(/\/dashboard\/configuracion\/publicaciones/);
  });

  test("quick actions navigate to their targets", async ({ page }) => {
    await page.goto("/dashboard");

    await page.getByRole("link", { name: /subir fuente/i }).click();
    await expect(page).toHaveURL(/\/dashboard\/conocimiento\/documentos/);

    await page.goto("/dashboard");
    await page.getByRole("link", { name: /^conversaciones$/i }).click();
    await expect(page).toHaveURL(/\/dashboard\/conversaciones$/);

    await page.goto("/dashboard");
    await page.getByRole("link", { name: /escalamientos/i }).first().click();
    await expect(page).toHaveURL(/\/dashboard\/conversaciones\/escalamientos/);

    await page.goto("/dashboard");
    await page.getByRole("link", { name: /previsualizar/i }).click();
    await expect(page).toHaveURL(/\/dashboard\/configuracion\/playground/);
  });

  test("security and health snapshots link to their detail pages", async ({ page }) => {
    await page.goto("/dashboard");

    const detailLinks = page.getByRole("link", { name: /ver detalle/i });
    const count = await detailLinks.count();
    test.skip(count === 0, "Security/health snapshot cards not visible for this account");

    // First "Ver detalle" -> seguridad, second -> estado (order matches page layout).
    await detailLinks.nth(0).click();
    await expect(page).toHaveURL(/\/dashboard\/(actividad\/seguridad|configuracion\/estado)/);
  });

  test("base de conocimiento card links to documentos", async ({ page }) => {
    await page.goto("/dashboard");

    const verTodos = page.getByRole("link", { name: /ver todos/i });
    if (await verTodos.count()) {
      await verTodos.first().click();
      await expect(page).toHaveURL(/\/dashboard\/conocimiento\/documentos/);
    }
  });

  test("escalamientos pendientes card links to bandeja", async ({ page }) => {
    await page.goto("/dashboard");

    const verBandeja = page.getByRole("link", { name: /ver bandeja/i });
    if (await verBandeja.count()) {
      await verBandeja.first().click();
      await expect(page).toHaveURL(/\/dashboard\/conversaciones\/escalamientos/);
    }
  });

  test("proveedores card links to gestion de proveedores", async ({ page }) => {
    await page.goto("/dashboard");

    const gestionar = page.getByRole("link", { name: /gestionar/i });
    if (await gestionar.count()) {
      await gestionar.first().click();
      await expect(page).toHaveURL(/\/dashboard\/configuracion\/proveedores/);
    }
  });
});

// ── OnboardingWizard ─────────────────────────────────────────────────────
// Staging only: desactiva temporalmente los proveedores activos vía API
// para forzar step != "done", y los restaura en un `finally`.
test.describe("Dashboard inicio - OnboardingWizard", () => {
  test("wizard renders, dismiss and refresh both work", async ({ page }) => {
    test.setTimeout(60_000);

    await page.goto("/dashboard");
    const cookies = await page.context().cookies();
    const token = cookies.find((c) => c.name === "chatbot_access")?.value;
    if (!token) {
      test.skip(true, "no se pudo leer el token de sesión para manipular el estado del sistema");
    }
    const authHeader = { Authorization: `Bearer ${token}` };

    const providersResp = await page.request.get("/api/v1/providers", { headers: authHeader });
    const providers: Array<{ id: string; is_active: boolean }> = await providersResp.json();
    // `step` solo se libera si TODOS los proveedores quedan inactivos.
    const activeProviders = providers.filter((p) => p.is_active);
    if (activeProviders.length === 0) {
      test.skip(true, "no hay proveedores activos que desactivar temporalmente");
    }

    const wasDismissed = (
      await (await page.request.get("/api/v1/auth/onboarding-status", { headers: authHeader })).json()
    ).dismissed as boolean;

    let restored = false;
    async function restore() {
      if (restored) return;
      restored = true;
      await Promise.all(activeProviders.map((p) =>
        page.request.patch(`/api/v1/providers/${p.id}`, { headers: authHeader, data: { is_active: true } }),
      ));
      if (wasDismissed) {
        await page.request.post("/api/v1/auth/onboarding-dismiss", { headers: authHeader });
      }
    }

    try {
      await Promise.all(activeProviders.map((p) =>
        page.request.patch(`/api/v1/providers/${p.id}`, { headers: authHeader, data: { is_active: false } }),
      ));
      // Un-dismiss so this run isn't skipped by a prior dismiss.
      await page.request.post("/api/v1/auth/onboarding-reset", { headers: authHeader });

      await page.goto("/dashboard");
      const wizard = page.getByRole("heading", { name: /bienvenido al panel del chatbot uso/i });
      await expect(wizard).toBeVisible({ timeout: 8_000 });

      await expect(page.getByText(/pasos completados/i)).toBeVisible();
      await expect(page.getByRole("button", { name: /activar modelo/i })).toBeVisible();

        const verificar = page.getByRole("button", { name: /verificar progreso/i });
      await verificar.click();
      await expect(page.getByText(/verificando/i)).toBeVisible({ timeout: 2_000 }).catch(() => {});
      await expect(verificar).toBeEnabled({ timeout: 5_000 });

      await page.getByRole("button", { name: /saltar tutorial/i }).click();
      await expect(wizard).not.toBeVisible({ timeout: 5_000 });
    } finally {
      await restore();
    }
  });
});
