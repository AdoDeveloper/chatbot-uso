import { describe, expect, it } from "vitest";
import { filenameFromDisposition } from "@/lib/utils";

describe("filenameFromDisposition", () => {
  it("decodifica filename* en minúsculas sin dejar el prefijo de charset", () => {
    expect(filenameFromDisposition("attachment; filename*=utf-8''Preguntas_Frecuentes.docx", "x"))
      .toBe("Preguntas_Frecuentes.docx");
  });

  it("decodifica caracteres no ASCII", () => {
    expect(filenameFromDisposition("attachment; filename*=UTF-8''Reglamento%20de%20Graduaci%C3%B3n.docx", "x"))
      .toBe("Reglamento de Graduación.docx");
  });

  it("prefiere filename* cuando vienen ambos", () => {
    expect(filenameFromDisposition(`attachment; filename="a.pdf"; filename*=utf-8''b%C3%A9.pdf`, "x"))
      .toBe("bé.pdf");
  });

  it("lee filename con y sin comillas", () => {
    expect(filenameFromDisposition('attachment; filename="reporte.xlsx"', "x")).toBe("reporte.xlsx");
    expect(filenameFromDisposition("attachment; filename=reporte.pdf", "x")).toBe("reporte.pdf");
  });

  it("usa el respaldo sin cabecera", () => {
    expect(filenameFromDisposition(undefined, "respaldo.json")).toBe("respaldo.json");
  });
});
