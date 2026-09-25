import { beforeAll, describe, expect, it } from "vitest";
import { renderMarkdown } from "@/lib/render-markdown";

function toDom(html: string): HTMLElement {
  const div = document.createElement("div");
  div.innerHTML = html;
  return div;
}

describe("renderMarkdown", () => {
  beforeAll(async () => {
    await import("dompurify");
    await new Promise((resolve) => setTimeout(resolve, 0));
  });

  it("muestra las imágenes con su texto alternativo", () => {
    const img = toDom(renderMarkdown("![Logo de la universidad](https://usonsonate.edu.sv/logo.png)")).querySelector("img");
    expect(img?.getAttribute("src")).toBe("https://usonsonate.edu.sv/logo.png");
    expect(img?.getAttribute("alt")).toBe("Logo de la universidad");
  });

  it("marca los enlaces a PDF y los abre en una pestaña nueva", () => {
    const a = toDom(renderMarkdown("[Aranceles 2025](https://usonsonate.edu.sv/aranceles.pdf)")).querySelector("a");
    expect(a?.classList.contains("pdf-link")).toBe(true);
    expect(a?.getAttribute("target")).toBe("_blank");
    expect(a?.getAttribute("rel")).toContain("noopener");
    expect(a?.textContent).toBe("Aranceles 2025");
  });

  it("si el enlace a PDF no tiene nombre, muestra un nombre genérico en lugar de la URL", () => {
    const a = toDom(renderMarkdown("https://usonsonate.edu.sv/aranceles.pdf")).querySelector("a");
    expect(a?.textContent).toBe("Documento PDF");
  });

  it("los enlaces que no son PDF no llevan el estilo de documento", () => {
    const a = toDom(renderMarkdown("[Sitio](https://usonsonate.edu.sv/tramites)")).querySelector("a");
    expect(a?.classList.contains("pdf-link")).toBe(false);
  });

  it("elimina enlaces e imágenes con javascript: y atributos de evento", () => {
    const dom = toDom(renderMarkdown(
      "[clic](javascript:alert(1)) ![x](javascript:alert(2)) <img src=x onerror=\"alert(3)\">",
    ));
    for (const el of Array.from(dom.querySelectorAll("a, img"))) {
      expect(el.getAttribute("href") ?? "").not.toMatch(/^javascript:/i);
      expect(el.getAttribute("src") ?? "").not.toMatch(/^javascript:/i);
      expect(el.hasAttribute("onerror")).toBe(false);
    }
  });
});
