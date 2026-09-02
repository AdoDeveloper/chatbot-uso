import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

describe("logger", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.resetModules();
  });
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it("calls console.error in dev", async () => {
    vi.stubEnv("NODE_ENV", "development");
    const { logger } = await import("../logger");
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    logger.error("test error");
    expect(spy).toHaveBeenCalledWith("test error");
    spy.mockRestore();
  });

  it("does not call console.error in production", async () => {
    vi.stubEnv("NODE_ENV", "production");
    const { logger } = await import("../logger");
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    logger.error("should be silent");
    expect(spy).not.toHaveBeenCalled();
    spy.mockRestore();
  });

  it("calls console.info in dev", async () => {
    vi.stubEnv("NODE_ENV", "development");
    const { logger } = await import("../logger");
    const spy = vi.spyOn(console, "info").mockImplementation(() => {});
    logger.info("info msg");
    expect(spy).toHaveBeenCalledWith("info msg");
    spy.mockRestore();
  });
});
