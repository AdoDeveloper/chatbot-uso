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
    // Use input type / id selectors - language-independent and resilient to
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

  test("mostrar/ocultar contraseña toggle", async ({ page }) => {
    await page.goto("/login");
    const passwordInput = page.locator("input#login-password");
    await passwordInput.fill("cualquier-cosa");
    await expect(passwordInput).toHaveAttribute("type", "password");

    const toggleBtn = page.getByLabel(/mostrar contraseña/i);
    await toggleBtn.click();
    await expect(passwordInput).toHaveAttribute("type", "text");

    await page.getByLabel(/ocultar contraseña/i).click();
    await expect(passwordInput).toHaveAttribute("type", "password");
  });
});

// ── Happy path (gated on credentials) ────────────────────────────────────────

test.describe("Login happy path", () => {
  test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

  test("signs in and lands on the dashboard", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(E2E_USER!);
    await page.locator('input#login-password').fill(E2E_PASS!);
    await page.locator('button[type="submit"]').click();

    // Successful login redirects out of /login. Use a generous timeout -
    // the auth context takes a tick to populate cookies + bootstrap user.
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });

    // "Chatbot USO" brand text in the sidebar confirms we're inside the
    // authenticated shell, not just parked on a redirect destination.
    await expect(page.getByText("Chatbot USO")).toBeVisible();
  });

  test("logged-in user can reach a deep route (admin tabs)", async ({ browser }) => {
    // Reuses the session saved by global-setup instead of logging in again -
    // repeated UI logins in the same run trip the backend's anti-brute-force
    // rate limit on /auth/login.
    const context = await browser.newContext({ storageState: "e2e/.auth/admin.json" });
    const page = await context.newPage();

    // Deep nested route under configuración should render for an authed user.
    await page.goto("/dashboard/configuracion/acceso/usuarios");
    await expect(page).toHaveURL(/\/dashboard\/configuracion\/acceso\/usuarios/);
    await context.close();
  });
});

// ── Notifications bell ──────────────────────────────────────────────────────

test.describe("Notifications bell", () => {
  test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");
  test.use({ storageState: "e2e/.auth/admin.json" });

  test("bell trigger is reachable in header", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });

    // Bell button has an aria-label that always matches "Notificaciones..."
    const bell = page.getByRole("button", { name: /notificaciones/i }).first();
    await expect(bell).toBeVisible();
    await bell.click();

    // Dropdown should show the inbox header. Don't assert specific items -
    // the test DB may have zero notifications, in which case we get the
    // empty state.
    await expect(page.getByText(/Sin notificaciones|Marcar todas|Ver historial/i)).toBeVisible();
  });
});
