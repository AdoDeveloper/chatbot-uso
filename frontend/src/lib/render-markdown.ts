import { Marked } from "marked";

const _marked = new Marked({ breaks: true, gfm: true, async: false });
_marked.use({
  renderer: {
    link({ href, text }: { href: string; text: string }) {
      const isPdf = /\.pdf(\?.*)?$/i.test(href || "");
      const cls = isPdf ? ' class="pdf-link"' : "";
      return `<a href="${href}" target="_blank" rel="noopener noreferrer"${cls}>${text}</a>`;
    },
    image({ href, text }: { href: string; text: string }) {
      const src = href.startsWith("http") || href.startsWith("data:") || href.startsWith("/") ? href : `/uploads/${href}`;
      return `<img src="${src}" alt="${text || ""}" />`;
    },
  },
});

// DOMPurify necesita el DOM del navegador - se carga de forma perezosa solo en el cliente.
let _purify: ((html: string) => string) | null = null;
if (typeof window !== "undefined") {
  import("dompurify").then((m) => {
    _purify = (html: string) =>
      m.default.sanitize(html, {
        ADD_TAGS: ["img"],
        ADD_ATTR: ["target", "src", "alt", "width", "height", "title"],
      });
  });
}

function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Si DOMPurify aún no cargó (ventana breve tras el mount), renderizamos el
// Markdown como texto plano escapado en vez de inyectar `raw` sin sanitizar.
export function renderMarkdown(text: string): string {
  const raw = _marked.parse(text) as string;
  const wrapped = raw.replace(/<table>/gi, '<div class="table-wrap"><table>').replace(/<\/table>/gi, '</table></div>');
  if (!_purify) return escapeHtml(text);
  return _purify(wrapped);
}
