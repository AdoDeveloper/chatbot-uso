import { describe, it, expect } from "vitest";
import { getErrorMessage } from "../use-api";

describe("getErrorMessage", () => {
  it("extracts string detail from an axios-like error", () => {
    const err = { response: { data: { detail: "Correo o contraseña incorrectos" } } };
    expect(getErrorMessage(err)).toBe("Correo o contraseña incorrectos");
  });

  it("joins array detail with . ", () => {
    const err = {
      response: {
        data: {
          detail: [
            { msg: "email: campo requerido" },
            { msg: "password: mínimo 8 caracteres" },
          ],
        },
      },
    };
    const msg = getErrorMessage(err);
    expect(msg).toContain("campo requerido");
    expect(msg).toContain("mínimo 8 caracteres");
  });

  it("falls back when there is no response", () => {
    expect(getErrorMessage(new Error("network error"))).toBe(
      "No se pudo cargar la información. Inténtelo de nuevo más tarde.",
    );
  });

  it("falls back when detail is an unexpected type", () => {
    const err = { response: { data: { detail: 42 } } };
    expect(getErrorMessage(err)).toBe(
      "No se pudo cargar la información. Inténtelo de nuevo más tarde.",
    );
  });

  it("uses a custom fallback when provided", () => {
    const err = new Error("x");
    expect(getErrorMessage(err, "Algo salió mal")).toBe("Algo salió mal");
  });
});
