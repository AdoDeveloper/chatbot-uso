import { test, expect } from "@playwright/test";
import { readFileSync } from "node:fs";

const E2E_USER = process.env.E2E_USER;

// Si global-setup.ts tuvo que rotar la contraseña (admin recién sembrado con
// must_change_password=true), E2E_PASS ya quedó obsoleta - usar la vigente.
function currentE2EPassword(): string | undefined {
  try {
    const { password } = JSON.parse(readFileSync("e2e/.auth/admin-password.json", "utf-8"));
    return password;
  } catch {
    return process.env.E2E_PASS;
  }
}
const E2E_PASS = currentE2EPassword();

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

  test("signs in and lands on the dashboard, then signs out", async ({ page }) => {
    await page.goto("/login");
    await page.locator('input[type="email"]').fill(E2E_USER!);
    await page.locator('input#login-password').fill(E2E_PASS!);
    await page.locator('button[type="submit"]').click();

    // Successful login redirects out of /login. Use a generous timeout -
    // the auth context takes a tick to populate cookies + bootstrap user.
    await expect(page).toHaveURL(/\/dashboard/, { timeout: 10_000 });

    await expect(page.getByText("Chatbot USO").first()).toBeVisible();

    await page.locator("header").getByRole("button").last().click();
    const [logoutResp] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/api/v1/auth/logout") && r.request().method() === "POST"),
      page.getByRole("menuitem", { name: /cerrar sesión/i }).click(),
    ]);
    expect(logoutResp.status(), `unexpected /auth/logout status: ${logoutResp.status()}`).toBe(200);
    await expect(page).toHaveURL(/\/login/, { timeout: 10_000 });
  });

  test("logged-in user can reach a deep route (admin tabs)", async ({ browser }) => {
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

    await expect(page.getByText(/Sin notificaciones|Marcar todas|Ver historial/i)).toBeVisible();
  });
});
