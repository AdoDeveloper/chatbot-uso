import { test, expect } from "@playwright/test";

const E2E_USER = process.env.E2E_USER;
const E2E_PASS = process.env.E2E_PASS;

test.use({ storageState: "e2e/.auth/admin.json" });
test.skip(!E2E_USER || !E2E_PASS, "E2E_USER / E2E_PASS not set - skipping");

const BACKEND_URL = "http://127.0.0.1:8000";
const FAKE_UUID = "00000000-0000-0000-0000-000000000000";

async function authHeaderFor(page: import("@playwright/test").Page): Promise<string> {
  const cookies = await page.context().cookies();
  const token = cookies.find((c) => c.name === "chatbot_access")?.value;
  if (!token) test.skip(true, "no se pudo leer el token de sesión");
  return `Bearer ${token}`;
}

test.describe("Endpoints sin UI propia - camino feliz y errores", () => {
  test("GET /analytics/sources/quality", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);
    const resp = await request.get(`${BACKEND_URL}/api/v1/analytics/sources/quality`, {
      headers: { Authorization: authHeader },
    });
    expect(resp.ok(), `unexpected status: ${resp.status()}`).toBeTruthy();
    const body = await resp.json();
    expect(body).toBeTruthy();

    // Sin token: 401.
    const unauthResp = await request.get(`${BACKEND_URL}/api/v1/analytics/sources/quality`);
    expect(unauthResp.status()).toBe(401);
  });

  test("GET /audit/logs/{log_id}: camino feliz y 404", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);
    const listResp = await request.get(`${BACKEND_URL}/api/v1/audit/logs?page=1&page_size=1`, {
      headers: { Authorization: authHeader },
    });
    expect(listResp.ok()).toBeTruthy();
    const list = await listResp.json();
    const firstLog = list.logs?.[0] ?? list.items?.[0];
    test.skip(!firstLog, "no hay logs de auditoría en este entorno");

    const detailResp = await request.get(`${BACKEND_URL}/api/v1/audit/logs/${firstLog.id}`, {
      headers: { Authorization: authHeader },
    });
    expect(detailResp.ok(), `unexpected status: ${detailResp.status()}`).toBeTruthy();
    const detail = await detailResp.json();
    expect(detail.id).toBe(firstLog.id);

    const notFoundResp = await request.get(`${BACKEND_URL}/api/v1/audit/logs/${FAKE_UUID}`, {
      headers: { Authorization: authHeader },
    });
    expect(notFoundResp.status()).toBe(404);
  });

  test("GET /chunks/{point_id}: camino feliz y 404", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);
    const sourcesResp = await request.get(`${BACKEND_URL}/api/v1/sources?page_size=50`, {
      headers: { Authorization: authHeader },
    });
    expect(sourcesResp.ok()).toBeTruthy();
    const sources = await sourcesResp.json();
    const readySource = (sources.items ?? sources).find((s: { status: string; chunk_count: number }) =>
      s.status === "ready" && s.chunk_count > 0
    );
    test.skip(!readySource, "no hay fuentes con chunks indexados en este entorno");

    const chunksResp = await request.get(`${BACKEND_URL}/api/v1/chunks/source/${readySource.id}?page_size=1`, {
      headers: { Authorization: authHeader },
    });
    expect(chunksResp.ok()).toBeTruthy();
    const chunksList = await chunksResp.json();
    const firstChunk = chunksList.items?.[0] ?? chunksList.chunks?.[0];
    test.skip(!firstChunk, "la fuente no devolvió chunks");

    const detailResp = await request.get(`${BACKEND_URL}/api/v1/chunks/${firstChunk.id}`, {
      headers: { Authorization: authHeader },
    });
    expect(detailResp.ok(), `unexpected status: ${detailResp.status()}`).toBeTruthy();

    const notFoundResp = await request.get(`${BACKEND_URL}/api/v1/chunks/nonexistent-point-id-e2e`, {
      headers: { Authorization: authHeader },
    });
    expect(notFoundResp.status()).toBe(404);
  });

  test("GET /faq/{faq_id}: camino feliz y 404", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);
    const label = `E2E FAQ GET ${Date.now()}`;
    const createResp = await request.post(`${BACKEND_URL}/api/v1/faq`, {
      headers: { Authorization: authHeader, "Content-Type": "application/json" },
      data: { question: label, answer: "Respuesta de prueba E2E.", tags: [] },
    });
    expect(createResp.ok(), `create failed: ${createResp.status()}`).toBeTruthy();
    const created = await createResp.json();

    try {
      const getResp = await request.get(`${BACKEND_URL}/api/v1/faq/${created.id}`, {
        headers: { Authorization: authHeader },
      });
      expect(getResp.ok(), `unexpected status: ${getResp.status()}`).toBeTruthy();
      const fetched = await getResp.json();
      expect(fetched.question).toBe(label);

      const notFoundResp = await request.get(`${BACKEND_URL}/api/v1/faq/${FAKE_UUID}`, {
        headers: { Authorization: authHeader },
      });
      expect(notFoundResp.status()).toBe(404);
    } finally {
      await request.delete(`${BACKEND_URL}/api/v1/faq/${created.id}`, { headers: { Authorization: authHeader } });
    }
  });

  test("GET /sources/{source_id}: camino feliz y 404", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);
    const listResp = await request.get(`${BACKEND_URL}/api/v1/sources?page_size=1`, {
      headers: { Authorization: authHeader },
    });
    expect(listResp.ok()).toBeTruthy();
    const list = await listResp.json();
    const firstSource = (list.items ?? list)[0];
    test.skip(!firstSource, "no hay fuentes en este entorno");

    const detailResp = await request.get(`${BACKEND_URL}/api/v1/sources/${firstSource.id}`, {
      headers: { Authorization: authHeader },
    });
    expect(detailResp.ok(), `unexpected status: ${detailResp.status()}`).toBeTruthy();
    const detail = await detailResp.json();
    expect(detail.id).toBe(firstSource.id);

    const notFoundResp = await request.get(`${BACKEND_URL}/api/v1/sources/${FAKE_UUID}`, {
      headers: { Authorization: authHeader },
    });
    expect(notFoundResp.status()).toBe(404);
  });

  test("GET /users/{user_id}: camino feliz y 404", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);
    const meResp = await request.get(`${BACKEND_URL}/api/v1/auth/me`, { headers: { Authorization: authHeader } });
    expect(meResp.ok()).toBeTruthy();
    const me = await meResp.json();

    const detailResp = await request.get(`${BACKEND_URL}/api/v1/users/${me.id}`, {
      headers: { Authorization: authHeader },
    });
    expect(detailResp.ok(), `unexpected status: ${detailResp.status()}`).toBeTruthy();
    const detail = await detailResp.json();
    expect(detail.id).toBe(me.id);

    const notFoundResp = await request.get(`${BACKEND_URL}/api/v1/users/${FAKE_UUID}`, {
      headers: { Authorization: authHeader },
    });
    expect(notFoundResp.status()).toBe(404);
  });

  test("GET /versions/{version_id}: camino feliz y 404", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);
    const listResp = await request.get(`${BACKEND_URL}/api/v1/versions?page_size=1`, {
      headers: { Authorization: authHeader },
    });
    expect(listResp.ok()).toBeTruthy();
    const list = await listResp.json();
    const firstVersion = (list.versions ?? list.items ?? list)[0];
    test.skip(!firstVersion, "no hay versiones en este entorno");

    const detailResp = await request.get(`${BACKEND_URL}/api/v1/versions/${firstVersion.id}`, {
      headers: { Authorization: authHeader },
    });
    expect(detailResp.ok(), `unexpected status: ${detailResp.status()}`).toBeTruthy();
    const detail = await detailResp.json();
    expect(detail.id).toBe(firstVersion.id);
    expect(detail).toHaveProperty("config_snapshot");

    const notFoundResp = await request.get(`${BACKEND_URL}/api/v1/versions/${FAKE_UUID}`, {
      headers: { Authorization: authHeader },
    });
    expect(notFoundResp.status()).toBe(404);
  });

  test("GET /rbac/my-permissions", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);
    const resp = await request.get(`${BACKEND_URL}/api/v1/rbac/my-permissions`, {
      headers: { Authorization: authHeader },
    });
    expect(resp.ok(), `unexpected status: ${resp.status()}`).toBeTruthy();
    const body = await resp.json();
    expect(body.role).toBeTruthy();
    expect(Array.isArray(body.permissions)).toBe(true);
    expect(body.permissions.length).toBeGreaterThan(0);

    const unauthResp = await request.get(`${BACKEND_URL}/api/v1/rbac/my-permissions`);
    expect(unauthResp.status()).toBe(401);
  });

  test("GET /integrations/smtp", async ({ page, request }) => {
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);
    const resp = await request.get(`${BACKEND_URL}/api/v1/integrations/smtp`, {
      headers: { Authorization: authHeader },
    });
    expect(resp.ok(), `unexpected status: ${resp.status()}`).toBeTruthy();
    const body = await resp.json();
    expect(body).toHaveProperty("configured");
    expect(typeof body.configured).toBe("boolean");
  });

  test("GET /health y /health/ready: publicos, sin auth", async ({ request }) => {
    const healthResp = await request.get(`${BACKEND_URL}/api/v1/health`);
    expect(healthResp.ok(), `unexpected status: ${healthResp.status()}`).toBeTruthy();

    const readyResp = await request.get(`${BACKEND_URL}/api/v1/health/ready`);
    expect([200, 503]).toContain(readyResp.status());
    const readyBody = await readyResp.json();
    expect(readyBody).toHaveProperty("checks");
    expect(readyBody.checks).toHaveProperty("mysql");
    expect(readyBody.checks).toHaveProperty("redis");
    expect(readyBody.checks).toHaveProperty("qdrant");
  });

  test("PATCH /conversations/{id}/status y POST /conversations/{id}/csat sobre una conversacion desechable", async ({ page, request }) => {
    test.setTimeout(60_000);
    await page.goto("/dashboard");
    const authHeader = await authHeaderFor(page);

    const cfgResp = await request.get(`${BACKEND_URL}/api/v1/widget/config`, { headers: { Authorization: authHeader } });
    expect(cfgResp.ok()).toBeTruthy();
    const widgetKey = (await cfgResp.json()).api_key as string;

    const chatResp = await request.post(`${BACKEND_URL}/api/v1/widget/public/chat`, {
      headers: { "X-Widget-Key": widgetKey },
      data: { question: `E2E status/csat probe ${Date.now()}`, session_id: `e2e-status-csat-${Date.now()}` },
    });
    expect(chatResp.ok(), `chat seed failed: ${chatResp.status()}`).toBeTruthy();
    const conversationId = (await chatResp.json()).conversation_id as string;

    try {
      // status: camino feliz (active -> resolved) y 404.
      const statusResp = await request.patch(`${BACKEND_URL}/api/v1/conversations/${conversationId}/status`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { status: "resolved" },
      });
      expect(statusResp.ok(), `unexpected status endpoint status: ${statusResp.status()}`).toBeTruthy();
      const statusBody = await statusResp.json();
      expect(statusBody.status).toBe("resolved");

      const status404 = await request.patch(`${BACKEND_URL}/api/v1/conversations/${FAKE_UUID}/status`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { status: "active" },
      });
      expect(status404.status()).toBe(404);

      const statusInvalid = await request.patch(`${BACKEND_URL}/api/v1/conversations/${conversationId}/status`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { status: "not-a-real-status" },
      });
      expect(statusInvalid.status()).toBe(422);

      // csat: camino feliz, 404, y score fuera de rango (400, no 422 - lo
      // valida el servicio a mano, no un schema de Pydantic).
      const csatResp = await request.post(`${BACKEND_URL}/api/v1/conversations/${conversationId}/csat`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { score: 4 },
      });
      expect(csatResp.ok(), `unexpected csat status: ${csatResp.status()}`).toBeTruthy();
      const csatBody = await csatResp.json();
      expect(csatBody.csat_score).toBe(4);

      const csat404 = await request.post(`${BACKEND_URL}/api/v1/conversations/${FAKE_UUID}/csat`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { score: 3 },
      });
      expect(csat404.status()).toBe(404);

      const csatOutOfRange = await request.post(`${BACKEND_URL}/api/v1/conversations/${conversationId}/csat`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { score: 99 },
      });
      expect(csatOutOfRange.status()).toBe(400);
    } finally {
      await request.post(`${BACKEND_URL}/api/v1/conversations/bulk`, {
        headers: { Authorization: authHeader, "Content-Type": "application/json" },
        data: { conversation_ids: [conversationId], action: "delete" },
      }).catch(() => {});
    }
  });
});
