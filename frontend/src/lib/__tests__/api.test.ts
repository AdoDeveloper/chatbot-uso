import { describe, it, expect } from "vitest";

import { apiUrl } from "../api";

describe("apiUrl", () => {
  it("prefixes /api/v1 to a leading-slash path", () => {
    expect(apiUrl("/audit/logs/export")).toMatch(/\/api\/v1\/audit\/logs\/export$/);
  });

  it("normalizes a path that doesn't start with a slash", () => {
    expect(apiUrl("audit/logs/export")).toMatch(/\/api\/v1\/audit\/logs\/export$/);
  });

  it("preserves the query string verbatim", () => {
    expect(apiUrl("/conversations/export?format=csv&status=active"))
      .toContain("?format=csv&status=active");
  });

  it("returns an absolute URL", () => {
    const out = apiUrl("/health");
    expect(out.startsWith("http")).toBe(true);
  });
});

describe("renovación de sesión entre pestañas", () => {
  it("usa los tokens que otra pestaña ya renovó en vez de cerrar la sesión", async () => {
    const { default: axios } = await import("axios");
    const { vi } = await import("vitest");
    const { default: api, tokenStore } = await import("../api");

    tokenStore.set("access-viejo", "refresh-viejo");
    const seen: string[] = [];
    api.defaults.adapter = async (config) => {
      const auth = String(config.headers?.Authorization ?? "");
      seen.push(auth);
      if (auth === "Bearer access-viejo") {
        const err = Object.assign(new Error("401"), {
          config, response: { status: 401, data: {}, headers: {}, config, statusText: "" },
        });
        throw err;
      }
      return { data: { ok: true }, status: 200, statusText: "OK", headers: {}, config };
    };
    const post = vi.spyOn(axios, "post").mockImplementation(async () => {
      tokenStore.set("access-nuevo", "refresh-nuevo");
      throw new Error("Refresh token ya utilizado");
    });

    const res = await api.get("/auth/me");

    expect(res.data).toEqual({ ok: true });
    expect(seen.at(-1)).toBe("Bearer access-nuevo");
    expect(tokenStore.getRefresh()).toBe("refresh-nuevo");
    post.mockRestore();
    tokenStore.clear();
  });
});
