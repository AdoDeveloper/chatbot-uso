import { describe, it, expect } from "vitest";

import { apiUrl, UPLOAD_LIMITS } from "../api";

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

describe("UPLOAD_LIMITS", () => {
  it("matches the values declared on the backend", () => {
    // Mirrors MAX_SOURCE_UPLOAD_MB in backend/app/core/config.py so the
    // frontend can validate file.size before upload.
    expect(UPLOAD_LIMITS.source_mb).toBe(50);
  });
});
