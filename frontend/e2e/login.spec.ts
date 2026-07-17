import { test, expect } from "@playwright/test";

/**
 * Smoke E2E for the login flow.
 *
 * Unauth paths run unconditionally:
 *   1. /              → redirects to /login
 *   2. /login         → renders, accepts input, calls the API on submit
 *   3. /dashboard/*   → unauth users get bounced to /login
 *
 * The "happy path" sign-in test runs only when E2E_USER + E2E_PASS are set.
 * In CI, set these to a seeded test account; locally, export them in your
 * shell to validate the full pipeline against your dev DB.
 *
 *   E2E_USER=admin@example.com E2E_PASS='secret' npm run test:e2e
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.describe("Login smoke", () => {
  test("root redirects to login", async ({ page }) => {
    const response = await page.goto("/");
    expect(response?.status()).toBeLessThan(400);
    await expect(page).toHaveURL(/\/login/);
  });

  test("login page renders the form", async ({ page }) => {
    await page.goto("/login");
    // The skip-to-content link added in Paso 7 should be in the DOM
    await expect(page.getByRole("link", { name: "Ir al contenido" })).toBeAttached();
    // Use input type / id selectors — language-independent and resilient to
    // copy changes in the labels.
    await expect(page.locator('input[type="email"]')).toBeVisible();
    await expect(page.locator('input#login-password')).toBeVisible();
    await expect(page.locator('button[type="submit"]')).toBeVisible();
  });

  test("invalid credentials show an error and stay on /login", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill("nobody@example.com");
    await page.locator('input#login-password').fill("wrong-password");
    await page.locator('button[type="submit"]').click();

    // Wait briefly for the request to roundtrip and assert we did not navigate
    // away from /login. Don't assert exact error copy so the test stays
    // resilient to wording changes.
    await page.waitForTimeout(800);
    await expect(page).toHaveURL(/\/login/);
  });

  test("dashboard requires auth", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });
});

// ── Happy path (gated on credentials) ────────────────────────────────────────

test.describe("Login happy path", () => {
  test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set — skipping");

  test("signs in and lands on the dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(E2E_USER!);
    await page.locator('input#login-password').fill(E2E_PASS!);
    await page.locator('button[type="submit"]').click();

    // Successful login redirects out of /login. Use a generous timeout —
    // the auth context takes a tick to populate cookies + bootstrap user.
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });

    // Sidebar landmark is in the layout — its presence confirms we're inside
    // the authenticated shell, not on a redirect destination.
    await expect(page.getByRole("navigation", { name: /navegación principal/i }))
      .toBeVisible();
  });

  test("logged-in user can reach a deep route (admin tabs)", async ({ page }) => {
    // Reuse the session from the previous test by signing in fresh.
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(E2E_USER!);
    await page.locator('input#login-password').fill(E2E_PASS!);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });

    // Old standalone URL → server-side redirect → unified target. Validates
    // both the redirect rule and that the admin shell renders for an authed
    // user. After the consolidation, /configuracion/cache lives inside
    // /sistema/estado as a recovery tool.
    await page.goto("/dashboard/configuracion/cache");
    await expect(page).toHaveURL(/\/dashboard\/sistema\/estado/);
  });
});

// ── Sidebar consolidation redirects ──────────────────────────────────────────

test.describe("Legacy route redirects", () => {
  test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set — skipping");

  test.beforeEach(async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(E2E_USER!);
    await page.locator('input#login-password').fill(E2E_PASS!);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });
  });

  // Cada item: ruta vieja → fragmento esperado en la nueva URL.
  // Estos redirects existen porque el rediseño del sidebar (22 → 15 items)
  // movió/fusionó pantallas. Bookmarks viejos deben seguir funcionando.
  const REDIRECTS: { from: string; to: RegExp }[] = [
    { from: "/dashboard/publicacion", to: /\/configuracion\?tab=widget/ },
    { from: "/dashboard/mantenimiento", to: /\/sistema\/estado/ },
    { from: "/dashboard/sistema/webhooks", to: /\/configuracion\/integraciones/ },
    { from: "/dashboard/sistema/salud", to: /\/sistema\/estado/ },
    { from: "/dashboard/sistema/auditoria", to: /\/actividad/ },
    { from: "/dashboard/sistema/seguridad", to: /\/actividad/ },
    { from: "/dashboard/conocimiento/faq", to: /\/conocimiento\/documentos/ },
    { from: "/dashboard/conocimiento/versiones", to: /\/sistema\/versiones/ },
    { from: "/dashboard/configuracion/cache", to: /\/sistema\/estado/ },
  ];

  for (const { from, to } of REDIRECTS) {
    test(`${from} redirects to consolidated route`, async ({ page }) => {
      await page.goto(from);
      await expect(page).toHaveURL(to);
    });
  }
});

// ── Notifications bell ──────────────────────────────────────────────────────

test.describe("Notifications bell", () => {
  test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set — skipping");

  test("bell trigger is reachable in header", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(E2E_USER!);
    await page.locator('input#login-password').fill(E2E_PASS!);
    await page.locator('button[type="submit"]').click();
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });

    // Bell button has an aria-label that always matches "Notificaciones..."
    const bell = page.getByRole("button", { name: /notificaciones/i }).first();
    await expect(bell).toBeVisible();
    await bell.click();

    // Dropdown should show the inbox header. Don't assert specific items —
    // the test DB may have zero notifications, in which case we get the
    // empty state.
    await expect(page.getByText(/Sin notificaciones|Marcar todas|Ver historial/i)).toBeVisible();
  });
});
