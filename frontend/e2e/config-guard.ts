import type { Page } from "@playwright/test";

const BACKEND_URL = "http://127.0.0.1:8000";
const SKIP = new Set(["id", "api_key", "created_at", "updated_at", "warnings"]);

export async function guardConfig(page: Page, endpoints: string[]) {
  const token = (await page.context().cookies()).find((c) => c.name === "chatbot_access")?.value;
  const headers = { Authorization: `Bearer ${token}` };
  const before = await Promise.all(endpoints.map(async (e) => (await page.request.get(BACKEND_URL + e, { headers })).json()));
  return async () => {
    for (const [i, endpoint] of endpoints.entries()) {
      const now = await (await page.request.get(BACKEND_URL + endpoint, { headers })).json();
      const changes = Object.fromEntries(Object.entries(before[i]).filter(([k, v]) =>
        !SKIP.has(k) && JSON.stringify(v) !== JSON.stringify(now[k])));
      if (Object.keys(changes).length) await page.request.put(BACKEND_URL + endpoint, { headers, data: changes });
    }
  };
}
