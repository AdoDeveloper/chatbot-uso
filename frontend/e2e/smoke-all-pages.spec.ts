import { test, expect } from "@playwright/test";

/**
 * Full-system smoke: every real page under /dashboard, mapped directly from
 * the app router file tree (`find frontend/src/app/(dashboard)/dashboard -name
 * page.tsx`), not from the sidebar - the sidebar can hide routes that still
 * exist and are reachable by direct URL.
 *
 * For each route: response is not an error status, no uncaught console
 * errors, no infinite loading spinner left behind, and a visual baseline.
 * Deliberately does NOT exercise create/edit/delete flows per page - those
 * are covered by the dedicated specs (conversaciones, invitaciones,
 * tablas-acciones) and by the backend test suite. This just proves every
 * page loads and renders without breaking.
 */
const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const ROUTES = [
  "/dashboard",
  "/dashboard/estadisticas",
  "/dashboard/reportes",
  "/dashboard/conversaciones",
  "/dashboard/conversaciones/escalamientos",
  "/dashboard/conversaciones/pendientes",
  "/dashboard/conocimiento/documentos",
  "/dashboard/conocimiento/consulta",
  "/dashboard/actividad",
  "/dashboard/actividad/auditoria",
  "/dashboard/actividad/inyecciones",
  "/dashboard/actividad/seguridad",
  "/dashboard/configuracion",
  "/dashboard/configuracion/asistente",
  "/dashboard/configuracion/cuotas",
  "/dashboard/configuracion/escalamiento",
  "/dashboard/configuracion/estado",
  "/dashboard/configuracion/filtros",
  "/dashboard/configuracion/notificaciones",
  "/dashboard/configuracion/playground",
  "/dashboard/configuracion/proveedores",
  "/dashboard/configuracion/publicaciones",
  "/dashboard/configuracion/widget",
  "/dashboard/configuracion/acceso",
  "/dashboard/configuracion/acceso/sso",
  "/dashboard/configuracion/acceso/usuarios",
];

for (const route of ROUTES) {
  test(`smoke: ${route}`, async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    const response = await page.goto(route);
    expect(response?.status(), `${route} returned an error status`).toBeLessThan(400);

    // `networkidle` is unreliable here - Next.js keeps background link-prefetch traffic going, so it can resolve before the page's own fetches finish. Wait out spinners directly instead.
    // /conocimiento/documentos legitimately keeps a spinning badge for rows still being processed by ingestion - real domain state, not a stuck loader, so it's excluded.
    if (route !== "/dashboard/conocimiento/documentos") {
      const spinners = page.locator(".animate-spin");
      await expect(spinners, `${route} left a loading spinner visible after settling`).toHaveCount(0, { timeout: 20_000 });
    }

    expect(consoleErrors, `${route} logged console errors:\n${consoleErrors.join("\n")}`).toEqual([]);

    const safeName = route.replace(/\//g, "_").replace(/^_/, "") || "root";
    await expect(page).toHaveScreenshot(`smoke-${safeName}.png`, {
      fullPage: true,
      maxDiffPixelRatio: 0.02,
    });
  });
}
