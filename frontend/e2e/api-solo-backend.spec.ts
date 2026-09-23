import { test, expect } from "@playwright/test";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const BACKEND_URL = "http://127.0.0.1:8000";

async function authHeaderFor(page: import("@playwright/test").Page): Promise<string> {
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === "chatbot_access")?.value;
  if (!token) test.skip(true, "no se pudo leer el token de sesión");
  return `Bearer ${token}`;
}

test.describe("API sin UI propia", () => {
  test("POST /alerts/run ejecuta los checks proactivos", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);

    const resp = await request.post(`${BACKEND_URL}/api/v1/alerts/run`, {
      headers: { Authorization: authHeader },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty("fired_by_check");
    expect(body).toHaveProperty("total_fired");
    expect(typeof body.total_fired).toBe("number");
  });

  test("POST /integrations/smtp/test valida el correo de prueba sin romper si SMTP no esta configurado", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);

    const resp = await request.post(`${BACKEND_URL}/api/v1/integrations/smtp/test`, {
      headers: { Authorization: authHeader, "Content-Type": "application/json" },
      data: { to: "e2e-smtp-test@invalid.example" },
    });
    expect(resp.ok()).toBeTruthy();
    const body = await resp.json();
    expect(typeof body.success).toBe("boolean");
    expect(typeof body.message).toBe("string");
  });

  test("PUT /conversations/{id}/tags reemplaza los tags de una conversacion", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);

    const listResp = await request.get(`${BACKEND_URL}/api/v1/conversations?page_size=1`, {
      headers: { Authorization: authHeader },
    });
    expect(listResp.ok()).toBeTruthy();
    const list = await listResp.json();
    const conv = list.items?.[0];
    if (!conv) test.skip(true, "no hay conversaciones en este entorno para probar el endpoint de tags");

    const originalTags: string[] = conv.tags ?? [];
    const testTag = `e2e-tag-${Date.now()}`;

    try {
      const setResp = await request.put(`${BACKEND_URL}/api/v1/conversations/${conv.id}/tags`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { tags: [testTag] },
      });
      expect(setResp.ok()).toBeTruthy();
      const setBody = await setResp.json();
      expect(setBody.tags).toEqual([testTag]);
    } finally {
      await request.put(`${BACKEND_URL}/api/v1/conversations/${conv.id}/tags`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { tags: originalTags },
      });
    }
  });
});
