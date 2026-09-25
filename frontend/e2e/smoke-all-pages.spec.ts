import { test, expect } from "@playwright/test";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

// Páginas cuyo alto depende de los datos que dejan otros specs: sin captura de referencia.
const DYNAMIC_HEIGHT_ROUTES = new Set([
  "/dashboard",
  "/dashboard/conversaciones/escalamientos",
  "/dashboard/conversaciones/pendientes",
  "/dashboard/actividad/auditoria",
  "/dashboard/actividad/seguridad",
  "/dashboard/conversaciones",
  "/dashboard/configuracion",
  "/dashboard/configuracion/asistente",
  "/dashboard/configuracion/asistente/apariencia",
  "/dashboard/configuracion/notificaciones",
  "/dashboard/configuracion/acceso",
  "/dashboard/configuracion/acceso/sso",
  "/dashboard/configuracion/acceso/usuarios",
  "/dashboard/configuracion/estado",
  "/dashboard/configuracion/estado/cuotas",
  "/dashboard/configuracion/estado/cuotas/limites",
  "/dashboard/configuracion/estado/cuotas/tendencia",
  "/dashboard/configuracion/proveedores",
  "/dashboard/configuracion/publicaciones",
  "/dashboard/estadisticas",
]);

const ROUTES = [
  "/dashboard",
  "/dashboard/estadisticas",
  "/dashboard/reportes",
  "/dashboard/conversaciones",
  "/dashboard/conversaciones/escalamientos",
  "/dashboard/conversaciones/pendientes",
  "/dashboard/conocimiento/documentos",
  "/dashboard/conocimiento/documentos/faq",
  "/dashboard/conocimiento/consulta",
  "/dashboard/actividad",
  "/dashboard/actividad/auditoria",
  "/dashboard/actividad/inyecciones",
  "/dashboard/actividad/seguridad",
  "/dashboard/configuracion",
  "/dashboard/configuracion/asistente",
  "/dashboard/configuracion/asistente/apariencia",
  "/dashboard/configuracion/asistente/prompt",
  "/dashboard/configuracion/asistente/integracion",
  "/dashboard/configuracion/asistente/limites",
  "/dashboard/configuracion/asistente/previsualizar",
  "/dashboard/configuracion/escalamiento",
  "/dashboard/configuracion/estado",
  "/dashboard/configuracion/estado/cuotas",
  "/dashboard/configuracion/estado/cuotas/limites",
  "/dashboard/configuracion/estado/cuotas/tendencia",
  "/dashboard/configuracion/filtros",
  "/dashboard/configuracion/notificaciones",
  "/dashboard/configuracion/proveedores",
  "/dashboard/configuracion/publicaciones",
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

    // Documentos muestra un indicador girando mientras una fuente se procesa.
    if (route !== "/dashboard/conocimiento/documentos") {
      const spinners = page.locator(".animate-spin");
      await expect(spinners, `${route} left a loading spinner visible after settling`).toHaveCount(0, { timeout: 20_000 });
    }

    expect(consoleErrors, `${route} logged console errors:\n${consoleErrors.join("\n")}`).toEqual([]);

    if (!DYNAMIC_HEIGHT_ROUTES.has(route)) {
      const safeName = route.replace(/\//g, "_").replace(/^_/, "") || "root";
      await expect(page).toHaveScreenshot(`smoke-${safeName}.png`, {
        fullPage: true,
        maxDiffPixelRatio: 0.02,
      });
    }
  });
}
