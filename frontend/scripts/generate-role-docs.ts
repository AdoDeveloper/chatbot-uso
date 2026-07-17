/**
 * Genera un manual con capturas anotadas para los 3 roles del sistema
 * (admin, editor, viewer): inicia sesión como cada uno, navega únicamente las
 * vistas visibles para ese rol, marca con un recuadro numerado el control de
 * acción clave ("Antes"), EJECUTA la acción real (crea un usuario/rol/regla/
 * proveedor/documento de prueba de verdad, o guarda un cambio real) y captura
 * el resultado real ("Después": toast de éxito, fila nueva, contador
 * actualizado). Los datos de prueba creados quedan persistidos en el sistema
 * — no se limpian al terminar (ambiente de prueba, según el usuario).
 *
 * Arma un documento Word por rol (con página de leyenda inicial) y un
 * README.md. El .docx fija tamaño de página y espaciado explícito entre
 * bloques para que las imágenes no se corten a mitad de página ni queden
 * pegadas al texto siguiente.
 *
 * Cada rol documenta TODAS sus vistas de forma completa e independiente,
 * incluso si una vista también es visible para otro rol — nunca se omite ni
 * se reemplaza por una referencia cruzada a otro documento.
 *
 * Requiere:
 *   - Backend + frontend corriendo (build de producción, no `next dev`: la
 *     CSP del proyecto bloquea `unsafe-eval`, que Next.js dev usa para HMR).
 *   - Variables de entorno con las credenciales de las 3 cuentas de prueba
 *     (ver carpeta de memoria del proyecto — no se versionan en el repo):
 *       DOCS_ADMIN_EMAIL / DOCS_ADMIN_PASSWORD
 *       DOCS_EDITOR_EMAIL / DOCS_EDITOR_PASSWORD
 *       DOCS_VIEWER_EMAIL / DOCS_VIEWER_PASSWORD
 *
 * Uso:
 *   PLAYWRIGHT_BASE_URL=http://localhost:3100 \
 *   DOCS_ADMIN_EMAIL=... DOCS_ADMIN_PASSWORD=... \
 *   DOCS_EDITOR_EMAIL=... DOCS_EDITOR_PASSWORD=... \
 *   DOCS_VIEWER_EMAIL=... DOCS_VIEWER_PASSWORD=... \
 *   npx tsx scripts/generate-role-docs.ts
 *
 * Salida: docs/roles/<rol>/*.png + docs/roles/<rol>.docx + docs/roles/README.md
 */
import { chromium, type Locator, type Page } from "@playwright/test";
import sharp from "sharp";
import {
  AlignmentType, Document, HeadingLevel, ImageRun, PageOrientation, Packer, Paragraph, TextRun,
} from "docx";
import { mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import path from "node:path";

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:3000";
const OUT_DIR = path.resolve(__dirname, "../../docs/roles");
const VIEWPORT = { width: 1440, height: 900 };
const MARK_COLOR = "#e11d48";

// Ancho objetivo de imagen dentro del docx, en px @96dpi. A4 con márgenes de
// 1" por lado deja ~6.27" de ancho útil (~602px) — se deja margen real para
// que Word nunca tenga que reescalar ni la imagen quede pegada al borde.
const DOCX_IMAGE_WIDTH = 460;
// Alto máximo de una imagen dentro del docx: una página A4 útil mide
// ~9.7" de alto (~930px). Con texto arriba (título + explicación) una
// imagen no debe superar ~620px o el salto de página la parte a la mitad.
const DOCX_IMAGE_MAX_HEIGHT = 620;

interface ActionSpec {
  /** Texto corto para el título del paso ("Antes: ..."). */
  description: string;
  /** Párrafo largo: qué hace el control y qué resultado espera el usuario. */
  explanation: string;
  /** Localiza el control a anotar en la captura "antes". */
  getLocator: (page: Page) => Locator | Promise<Locator>;
  /**
   * Ejecuta la acción real: clic real, llenar formulario real con datos de
   * prueba identificables, enviar de verdad. No se revierte después — los
   * datos de prueba quedan persistidos en el sistema (ambiente de prueba).
   * Debe dejar la página en un estado donde el resultado real sea visible
   * (toast, fila nueva, modal cerrado) para la captura "después".
   */
  execute: (page: Page) => Promise<void>;
}

interface ViewSpec {
  id: string;
  href: string;
  section: string;
  label: string;
  description: string;
  /** Controles de acción clave a ejecutar y documentar, en orden. */
  actions?: ActionSpec[];
}

interface RoleSpec {
  role: "admin" | "editor" | "viewer";
  displayName: string;
  summary: string;
  emailEnv: string;
  passwordEnv: string;
  views: ViewSpec[];
}

interface CapturedImage {
  fileName: string;
  absPath: string;
  widthPx: number;
  heightPx: number;
  /** "Antes" / "Después" / etiqueta corta mostrada en negrita antes de la imagen. */
  tag?: string;
  stepExplanation?: string;
}

interface ViewResult {
  view: ViewSpec;
  images: CapturedImage[];
}

const TEST_TAG = "Prueba manual";

// ─────────────────────────────────────────────────────────────────────────
// Definición de vistas por rol. Cada vista es visible en el rol donde
// aparece — se repite íntegramente entre roles a propósito, nunca se omite.
// ─────────────────────────────────────────────────────────────────────────

const COMMON_PRINCIPAL: Omit<ViewSpec, "id">[] = [
  { href: "/dashboard", section: "Principal", label: "Inicio",
    description: "Resumen general: métricas clave de conversaciones, documentos y estado del sistema." },
  { href: "/dashboard/conversaciones", section: "Principal", label: "Conversaciones",
    description: "Historial de conversaciones del chatbot con los usuarios finales." },
  { href: "/dashboard/estadisticas", section: "Principal", label: "Estadísticas",
    description: "Gráficas de uso: volumen de conversaciones, temas frecuentes, satisfacción." },
  { href: "/dashboard/reportes", section: "Principal", label: "Reportes",
    description: "Reportes exportables sobre el uso del chatbot." },
];

async function clickAndWaitToast(page: Page, buttonName: string | RegExp): Promise<void> {
  await page.getByRole("button", { name: buttonName }).first().click();
  await page.waitForTimeout(1200);
}

const DOCUMENTOS_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/conocimiento/documentos", section: "Conocimiento", label: "Documentos",
  description: "Base de conocimiento del chatbot: sube, edita y elimina los documentos fuente.",
  actions: [{
    description: `Haga clic en "Agregar" para subir un nuevo documento.`,
    explanation: "Este botón abre el panel para subir un nuevo documento (PDF, Word o Excel) a la base de " +
      "conocimiento. Una vez subido, el sistema lo procesa e indexa automáticamente para que el chatbot pueda " +
      "usarlo al responder preguntas de los usuarios.",
    getLocator: (page) => page.getByRole("button", { name: "Agregar" }).first(),
    execute: async (page) => {
      await page.getByRole("button", { name: "Agregar" }).first().click();
      await page.waitForTimeout(400);
      const pdfPath = path.join(OUT_DIR, "_test-doc.pdf");
      writeFileSync(pdfPath, MINIMAL_PDF);
      await page.locator('input[type="file"]').setInputFiles(pdfPath);
      await page.waitForTimeout(400);
      const nameField = page.getByPlaceholder(/Instructivo para alumnos/).first();
      if ((await nameField.count()) > 0) await nameField.fill(`${TEST_TAG} — documento.pdf`);
      await page.getByRole("button", { name: "Guardar" }).first().click();
      await page.waitForTimeout(1500);
    },
  }],
};

const CONSULTA_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/conocimiento/consulta", section: "Conocimiento", label: "Búsqueda",
  description: "Prueba manual de búsqueda semántica sobre los documentos cargados.",
};

const ASISTENTE_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/asistente", section: "Chatbot", label: "Asistente",
  description: "Prompt del sistema y comportamiento general del asistente conversacional.",
  actions: [{
    description: `Edite un campo y haga clic en "Guardar" para aplicar los cambios.`,
    explanation: "El prompt del sistema define cómo se comporta el asistente: su tono, qué información puede " +
      "usar y qué reglas debe seguir al responder. Tras editar cualquier campo, debe hacer clic en \"Guardar\" " +
      "para que el cambio tenga efecto en las conversaciones nuevas del chatbot.",
    getLocator: (page) => page.getByRole("button", { name: "Guardar" }).first(),
    execute: async (page) => {
      const field = page.locator('input:not([type="checkbox"]):not([type="radio"]):not([type="file"]):not([type="hidden"])')
        .locator("visible=true").first();
      await field.click();
      await field.press("End");
      await field.type(" ");
      await clickAndWaitToast(page, "Guardar");
    },
  }],
};

const PROVEEDORES_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/proveedores", section: "Chatbot", label: "Proveedores",
  description: "Configuración de los proveedores de modelos de lenguaje (LLM) usados por el chatbot.",
  actions: [{
    description: `Haga clic en "Agregar" para añadir un proveedor a la cadena.`,
    explanation: "Cada proveedor representa un modelo de lenguaje (LLM) que el chatbot puede usar para generar " +
      "respuestas. La cadena de proveedores define el orden de prioridad: si el primero falla, el sistema " +
      "intenta automáticamente con el siguiente. Este ejemplo agrega un proveedor Ollama de prueba (no requiere " +
      "API key) para ilustrar el flujo completo.",
    getLocator: (page) => page.getByRole("button", { name: "Agregar" }).first(),
    execute: async (page) => {
      await page.getByRole("button", { name: "Agregar" }).first().click();
      await page.waitForTimeout(400);
      await page.getByPlaceholder(/GPT-4o Producción/).fill(`${TEST_TAG} — Ollama`);
      const providerSelect = page.getByRole("combobox").first();
      await providerSelect.selectOption("ollama").catch(() => {});
      await page.waitForTimeout(300);
      const modelField = page.locator('input, select').filter({ hasText: "" }).nth(2);
      await modelField.fill("llama3").catch(() => {});
      await page.getByRole("button", { name: /Agregar|Guardar/ }).last().click();
      await page.waitForTimeout(1200);
    },
  }],
};

const WIDGET_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/widget", section: "Chatbot", label: "Widget",
  description: "Apariencia y comportamiento del widget de chat embebido en el sitio público.",
  actions: [{
    description: `Ajuste un campo y haga clic en "Guardar" para publicar los cambios.`,
    explanation: "Este panel controla cómo se ve y se comporta el widget de chat que los visitantes del sitio " +
      "público usan para hablar con el chatbot. Los cambios (colores, mensaje de bienvenida, posición) solo se " +
      "aplican al sitio público después de hacer clic en \"Guardar\".",
    getLocator: (page) => page.getByRole("button", { name: "Guardar" }).first(),
    execute: async (page) => {
      const field = page.locator('input:not([type="checkbox"]):not([type="radio"]):not([type="file"]):not([type="hidden"])')
        .locator("visible=true").first();
      await field.click();
      await field.press("End");
      await field.type(" ");
      await clickAndWaitToast(page, "Guardar");
    },
  }],
};

const PREVISUALIZAR_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/playground", section: "Chatbot", label: "Previsualizar",
  description: "Entorno de prueba para conversar con el chatbot antes de publicar cambios.",
};

const ESCALAMIENTO_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/escalamiento", section: "Chatbot", label: "Escalamiento",
  description: "Reglas para derivar conversaciones a personal humano.",
  actions: [{
    description: `Haga clic en "Agregar" para crear una nueva regla de escalamiento.`,
    explanation: "Una regla de escalamiento define en qué situaciones una conversación debe derivarse a una " +
      "persona en vez de que el chatbot siga respondiendo. Este ejemplo crea una regla que escala cuando el " +
      "usuario solicita explícitamente hablar con una persona.",
    getLocator: (page) => page.getByRole("button", { name: "Agregar" }).first(),
    execute: async (page) => {
      await page.getByRole("button", { name: "Agregar" }).first().click();
      await page.waitForTimeout(400);
      await page.getByPlaceholder("Nombre de la regla").fill(`${TEST_TAG} — escalar a soporte`);
      await page.getByRole("button", { name: "Guardar" }).last().click();
      await page.waitForTimeout(1200);
    },
  }],
};

const FILTROS_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/filtros", section: "Chatbot", label: "Filtros",
  description: "Filtros de contenido y guardrails que aplica el chatbot a las respuestas.",
  actions: [{
    description: `Haga clic en "Nuevo patrón" para crear un filtro de contenido adicional.`,
    explanation: "Un patrón de filtro define un tipo de contenido que el chatbot debe bloquear o marcar. Este " +
      "ejemplo crea un patrón de prueba que detecta la palabra \"prueba-manual\" en los mensajes, ilustrando el " +
      "flujo completo de creación de un patrón.",
    getLocator: (page) => page.getByRole("button", { name: "Nuevo patrón" }).first(),
    execute: async (page) => {
      await page.getByRole("button", { name: "Nuevo patrón" }).first().click();
      await page.waitForTimeout(400);
      await page.getByPlaceholder(/Bloque de exec\/eval/).fill(`${TEST_TAG} — patrón`);
      await page.getByPlaceholder(/eval\|exec/).fill("prueba-manual-docs");
      await page.getByRole("button", { name: /Crear|Guardar/ }).last().click();
      await page.waitForTimeout(1200);
    },
  }],
};

const PUBLICACIONES_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/publicaciones", section: "Chatbot", label: "Publicaciones",
  description: "Historial de versiones publicadas de la configuración del chatbot.",
  actions: [{
    description: `Haga clic en "Publicar a producción" para aplicar los cambios pendientes.`,
    explanation: "Los cambios hechos en Asistente, Proveedores, Widget, Escalamiento y Filtros quedan como " +
      "borrador hasta que se publican. Este botón aplica todos los cambios pendientes de una sola vez a la " +
      "versión que usan los usuarios finales del chatbot.",
    getLocator: (page) => page.getByRole("button", { name: /Publicar a producción/ }).first(),
    execute: async (page) => {
      await clickAndWaitToast(page, /Publicar a producción/);
    },
  }],
};

const CHATBOT_VIEWS: Omit<ViewSpec, "id">[] = [
  ASISTENTE_VIEW, PROVEEDORES_VIEW, WIDGET_VIEW, PREVISUALIZAR_VIEW,
  ESCALAMIENTO_VIEW, FILTROS_VIEW, PUBLICACIONES_VIEW,
];

const USUARIOS_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/acceso/usuarios", section: "Acceso", label: "Usuarios",
  description: "Alta, baja y edición de las cuentas del personal administrativo.",
  actions: [{
    description: `Haga clic en "Invitar usuario" para dar acceso a una nueva persona.`,
    explanation: "Este botón envía una invitación por correo a la persona indicada, con el rol que se le asigne " +
      "(Administrador, Editor o Lector). La persona recibe un enlace para crear su contraseña y acceder al panel.",
    getLocator: (page) => page.getByRole("button", { name: "Invitar usuario" }).first(),
    execute: async (page) => {
      await page.getByRole("button", { name: "Invitar usuario" }).first().click();
      await page.waitForTimeout(400);
      // Email único por corrida: User.email tiene restricción unique y una
      // corrida anterior ya crea la cuenta, causando 409 "El correo ya tiene cuenta".
      await page.getByPlaceholder("usuario@empresa.com").fill(`manual-demo-${Date.now()}@usonsonate.edu.sv`);
      await page.getByRole("button", { name: "Generar enlace" }).first().click();
      await page.waitForTimeout(1200);
    },
  }],
};

const ROLES_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/acceso/roles", section: "Acceso", label: "Roles",
  description: "Roles del sistema y roles personalizados adicionales.",
  actions: [{
    description: `Haga clic en "Nuevo rol" para crear un rol personalizado.`,
    explanation: "Además de los tres roles del sistema (Administrador, Editor, Lector), se pueden crear roles " +
      "personalizados con una combinación distinta de permisos. Tras crearlo, sus permisos se ajustan desde la " +
      "vista de Permisos.",
    getLocator: (page) => page.getByRole("button", { name: "Nuevo rol" }).first(),
    execute: async (page) => {
      await page.getByRole("button", { name: "Nuevo rol" }).first().click();
      await page.waitForTimeout(400);
      // Identificador único por corrida: el backend rechaza nombres de rol
      // duplicados, y una corrida anterior deja el mismo id persistido.
      await page.getByPlaceholder(/revisor_externo/).fill(`prueba_manual_docs_${Date.now()}`);
      await page.getByPlaceholder(/Revisor Externo/).fill(`${TEST_TAG} — rol`);
      await page.getByRole("button", { name: "Guardar" }).last().click();
      await page.waitForTimeout(1200);
    },
  }],
};

const PERMISOS_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/acceso/permisos", section: "Acceso", label: "Permisos",
  description: "Matriz de permisos por rol: qué puede ver y hacer cada rol en cada módulo.",
  actions: [{
    description: "Seleccione el rol Editor y active o desactive un permiso con este interruptor.",
    explanation: "Cada fila de la matriz representa un permiso específico (ver, crear, editar, eliminar) sobre " +
      "un módulo del sistema. El rol Administrador tiene todos los permisos bloqueados (no editables); para " +
      "otros roles, active el interruptor para conceder ese permiso, o desactívelo para revocarlo. El cambio " +
      "se aplica de inmediato a todos los usuarios con ese rol.",
    getLocator: async (page: Page) => {
      const editorTab = page.getByRole("button", { name: "Editor" }).first();
      if ((await editorTab.count()) > 0) await editorTab.click();
      return page.getByRole("switch").first();
    },
    execute: async (page) => {
      const editorTab = page.getByRole("button", { name: "Editor" }).first();
      if ((await editorTab.count()) > 0) {
        await editorTab.click();
        await page.waitForTimeout(300);
      }
      await page.getByRole("switch").first().click();
      await page.waitForTimeout(800);
    },
  }],
};

const SSO_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/acceso/sso", section: "Acceso", label: "Inicio de sesión",
  description: "Configuración del inicio de sesión institucional (SSO) con Microsoft.",
  actions: [{
    description: "Active o desactive el inicio de sesión con Microsoft con este interruptor.",
    explanation: "Este interruptor habilita que el personal inicie sesión con su cuenta institucional de " +
      "Microsoft 365, en vez de (o además de) correo y contraseña. Requiere que las credenciales de la " +
      "aplicación ya estén configuradas en el servidor.",
    getLocator: (page) => page.locator("text=Activar Microsoft SSO").locator("..").locator("..").getByRole("switch"),
    execute: async (page) => {
      await page.locator("text=Activar Microsoft SSO").locator("..").locator("..").getByRole("switch").click();
      await page.waitForTimeout(800);
    },
  }],
};

const NOTIFICACIONES_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/notificaciones", section: "Sistema", label: "Notificaciones",
  description: "Reglas de notificación por correo ante eventos del sistema.",
  actions: [{
    description: "Active o desactive una regla de notificación con este interruptor.",
    explanation: "Cada regla envía un correo al personal administrativo cuando ocurre un evento específico. " +
      "Active el interruptor para recibir esas notificaciones, o desactívelo para dejar de recibirlas.",
    getLocator: (page) => page.getByRole("switch").first(),
    execute: async (page) => {
      await page.getByRole("switch").first().click();
      await page.waitForTimeout(800);
    },
  }],
};

const CUOTAS_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/cuotas", section: "Sistema", label: "Cuotas",
  description: "Límites de uso (rate limiting) para proteger el sistema de abuso.",
  actions: [{
    description: `Ajuste un límite y haga clic en "Guardar" para aplicarlo.`,
    explanation: "Estos límites controlan cuántas solicitudes puede hacer un mismo usuario o sesión en un " +
      "período de tiempo, para evitar abuso o sobrecarga del sistema. El cambio se aplica desde el momento en " +
      "que se guarda, sin necesidad de reiniciar el servicio.",
    getLocator: (page) => page.getByRole("button", { name: "Guardar" }).first(),
    execute: async (page) => {
      const field = page.locator('input[type="number"]').first();
      if ((await field.count()) > 0) {
        const current = await field.inputValue();
        await field.fill(current);
      }
      await clickAndWaitToast(page, "Guardar");
    },
  }],
};

const ESTADO_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/estado", section: "Sistema", label: "Estado",
  description: "Salud de la infraestructura: base de datos, caché, motor de búsqueda vectorial.",
};

const INTEGRACIONES_VIEW: Omit<ViewSpec, "id"> = {
  href: "/dashboard/configuracion/integraciones", section: "Sistema", label: "Integraciones",
  description: "Conexión con sistemas externos (correo, SSO de Microsoft, etc.).",
  actions: [{
    description: `Si el correo (SMTP) ya está configurado, haga clic en "Enviar prueba" para verificarlo.`,
    explanation: "Este botón envía un correo de prueba usando la configuración SMTP actual, para confirmar que " +
      "el sistema puede enviar notificaciones e invitaciones por correo correctamente. Solo está disponible " +
      "cuando ya se configuraron las credenciales del servidor de correo.",
    getLocator: (page) => page.getByRole("button", { name: "Enviar prueba" }).first(),
    execute: async (page) => {
      await clickAndWaitToast(page, "Enviar prueba");
    },
  }],
};

const ROLES: RoleSpec[] = [
  {
    role: "admin",
    displayName: "Administrador",
    summary:
      "Acceso total al sistema: además de todo lo que ven Editor y Lector, gestiona usuarios, roles, " +
      "permisos, inicio de sesión (SSO), integraciones, notificaciones del sistema, cuotas de uso y el " +
      "estado de salud de la infraestructura.",
    emailEnv: "DOCS_ADMIN_EMAIL",
    passwordEnv: "DOCS_ADMIN_PASSWORD",
    views: [
      ...COMMON_PRINCIPAL.map((v) => ({ ...v, id: v.href })),
      { id: "actividad", href: "/dashboard/actividad", section: "Principal", label: "Actividad",
        description: "Auditoría de acciones administrativas, alertas de seguridad e intentos de inyección detectados." },
      { ...DOCUMENTOS_VIEW, id: "documentos" },
      { ...CONSULTA_VIEW, id: "consulta" },
      ...CHATBOT_VIEWS.map((v) => ({ ...v, id: v.label.toLowerCase() })),
      { ...INTEGRACIONES_VIEW, id: "integraciones" },
      { ...NOTIFICACIONES_VIEW, id: "notificaciones" },
      { ...CUOTAS_VIEW, id: "cuotas" },
      { ...ESTADO_VIEW, id: "estado" },
      { ...USUARIOS_VIEW, id: "usuarios" },
      { ...ROLES_VIEW, id: "roles" },
      { ...PERMISOS_VIEW, id: "permisos" },
      { ...SSO_VIEW, id: "sso" },
    ],
  },
  {
    role: "editor",
    displayName: "Editor",
    summary:
      "Gestiona el contenido y el comportamiento del chatbot: documentos, configuración del asistente, " +
      "escalamiento y estadísticas. No tiene acceso a la gestión de usuarios ni a la configuración de " +
      "infraestructura del sistema.",
    emailEnv: "DOCS_EDITOR_EMAIL",
    passwordEnv: "DOCS_EDITOR_PASSWORD",
    views: [
      ...COMMON_PRINCIPAL.map((v) => ({ ...v, id: v.href })),
      { ...DOCUMENTOS_VIEW, id: "documentos" },
      { ...CONSULTA_VIEW, id: "consulta" },
      ...CHATBOT_VIEWS.map((v) => ({ ...v, id: v.label.toLowerCase() })),
    ],
  },
  {
    role: "viewer",
    displayName: "Lector",
    summary:
      "Acceso de solo lectura a estadísticas e historial de conversaciones. No puede modificar documentos, " +
      "configuración del chatbot ni usuarios.",
    emailEnv: "DOCS_VIEWER_EMAIL",
    passwordEnv: "DOCS_VIEWER_PASSWORD",
    views: COMMON_PRINCIPAL.map((v) => ({ ...v, id: v.href })),
  },
];

// PDF de una página con texto real y tabla xref con offsets correctos —
// necesario para que el pipeline de ingestión del backend pueda extraer
// texto sin fallar, a diferencia de un PDF mínimo sin contenido real.
function buildMinimalPdf(): Buffer {
  const objects = [
    "<</Type/Catalog/Pages 2 0 R>>",
    "<</Type/Pages/Kids[3 0 R]/Count 1>>",
    "<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 4 0 R>>>>/Contents 5 0 R>>",
    "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
  ];
  // Timestamp incluido en el contenido: el backend deduplica por hash del
  // archivo, así que un texto fijo entre corridas provoca un 409 Conflict al
  // subir (ya existe un documento idéntico de una corrida anterior).
  const streamText = `BT /F1 18 Tf 72 720 Td (Documento de prueba manual - generado ${Date.now()}) Tj ET`;
  const streamObj = `<</Length ${streamText.length}>>\nstream\n${streamText}\nendstream`;

  const parts: string[] = ["%PDF-1.4\n"];
  const offsets: number[] = [];
  let cursor = parts[0].length;

  objects.forEach((body, i) => {
    offsets.push(cursor);
    const obj = `${i + 1} 0 obj\n${body}\nendobj\n`;
    parts.push(obj);
    cursor += obj.length;
  });
  offsets.push(cursor);
  const obj5 = `5 0 obj\n${streamObj}\nendobj\n`;
  parts.push(obj5);
  cursor += obj5.length;

  const xrefStart = cursor;
  let xref = `xref\n0 6\n0000000000 65535 f \n`;
  for (const off of offsets) xref += `${String(off).padStart(10, "0")} 00000 n \n`;
  parts.push(xref);

  parts.push(`trailer<</Size 6/Root 1 0 R>>\nstartxref\n${xrefStart}\n%%EOF`);

  return Buffer.from(parts.join(""), "utf-8");
}

const MINIMAL_PDF = buildMinimalPdf();

// ─────────────────────────────────────────────────────────────────────────
// Login
// ─────────────────────────────────────────────────────────────────────────

async function login(page: Page, email: string, password: string) {
  await page.goto(`${BASE_URL}/login`);
  await page.locator('input[type="email"]').fill(email);
  await page.locator('input#login-password').fill(password);
  await page.locator('button[type="submit"]').click();
  await page.waitForURL(/\/dashboard/, { timeout: 15_000 });
  await page.waitForTimeout(600);
}

// ─────────────────────────────────────────────────────────────────────────
// Captura simple del primer viewport (sin scroll) — usada tanto para el
// estado "antes"/"después" con anotación como para vistas de solo lectura.
// ─────────────────────────────────────────────────────────────────────────

async function captureViewport(page: Page, outDir: string, fileName: string): Promise<CapturedImage> {
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(150);
  const absPath = path.join(outDir, fileName);
  await page.screenshot({ path: absPath });
  const meta = await sharp(absPath).metadata();
  return { fileName, absPath, widthPx: meta.width ?? VIEWPORT.width, heightPx: meta.height ?? VIEWPORT.height };
}

// ─────────────────────────────────────────────────────────────────────────
// Anotación: recuadro + círculo numerado + flecha + etiqueta de texto sobre
// el control indicado, en la captura "antes" de ejecutar la acción.
// ─────────────────────────────────────────────────────────────────────────

/** Escapa texto para insertarlo de forma segura dentro de un <text> SVG. */
function escapeSvgText(s: string): string {
  return s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

/** Envuelve `text` en líneas de máximo `maxChars` caracteres (corte por palabra). */
function wrapText(text: string, maxChars: number): string[] {
  const words = text.split(/\s+/);
  const lines: string[] = [];
  let current = "";
  for (const w of words) {
    const candidate = current ? `${current} ${w}` : w;
    if (candidate.length > maxChars && current) {
      lines.push(current);
      current = w;
    } else {
      current = candidate;
    }
  }
  if (current) lines.push(current);
  return lines;
}

async function captureAnnotated(
  page: Page, locator: Locator, outDir: string, fileName: string,
  label?: string,
): Promise<CapturedImage | null> {
  const count = await locator.count();
  if (count === 0) return null;

  await locator.scrollIntoViewIfNeeded().catch(() => {});
  await page.waitForTimeout(150);
  const box = await locator.boundingBox();
  if (!box) return null;

  const absPath = path.join(outDir, fileName);
  await page.screenshot({ path: absPath });

  const meta = await sharp(absPath).metadata();
  const width = meta.width ?? VIEWPORT.width;
  const height = meta.height ?? VIEWPORT.height;

  const pad = 6;
  const rectX = Math.max(0, box.x - pad);
  const rectY = Math.max(0, box.y - pad);
  const rectW = Math.min(width - rectX, box.width + pad * 2);
  const rectH = Math.min(height - rectY, box.height + pad * 2);
  const badgeCx = Math.max(14, rectX);
  const badgeCy = Math.max(14, rectY);
  const targetCx = rectX + rectW / 2;
  const targetCy = rectY + rectH / 2;

  // Círculo de énfasis (además del recuadro): rodea el centro del control
  // con un óvalo punteado, reforzando visualmente dónde mirar.
  const ellipseRx = Math.max(rectW / 2 + 10, 28);
  const ellipseRy = Math.max(rectH / 2 + 10, 20);

  // Etiqueta de texto con fondo: se ubica arriba del control si hay espacio,
  // si no, abajo. Envuelve el texto en varias líneas cortas.
  const labelText = label ? wrapText(label, 34).slice(0, 3) : [];
  const labelLineH = 20;
  const labelPadding = 10;
  const labelW = Math.min(
    320,
    Math.max(120, Math.max(...labelText.map((l) => l.length), 0) * 8 + labelPadding * 2),
  );
  const labelH = labelText.length * labelLineH + labelPadding * 1.4;
  const spaceAbove = rectY;
  const placeAbove = spaceAbove > labelH + 30;
  const labelX = Math.min(Math.max(0, targetCx - labelW / 2), width - labelW);
  const labelY = placeAbove ? Math.max(4, rectY - labelH - 26) : Math.min(height - labelH - 4, rectY + rectH + 26);

  // Flecha curva desde el borde de la etiqueta hasta el borde del recuadro.
  const arrowStartX = labelX + labelW / 2;
  const arrowStartY = placeAbove ? labelY + labelH : labelY;
  const arrowEndX = targetCx;
  const arrowEndY = placeAbove ? rectY - 4 : rectY + rectH + 4;
  const arrowMidY = (arrowStartY + arrowEndY) / 2;

  const labelSvg = labelText.length
    ? `
      <rect x="${labelX}" y="${labelY}" width="${labelW}" height="${labelH}"
            fill="${MARK_COLOR}" fill-opacity="0.92" rx="8" />
      ${labelText.map((l, idx) => `
        <text x="${labelX + labelW / 2}" y="${labelY + labelPadding + (idx + 1) * labelLineH - 6}"
              font-family="sans-serif" font-size="14" font-weight="600" fill="white"
              text-anchor="middle">${escapeSvgText(l)}</text>
      `).join("")}
      <path d="M ${arrowStartX} ${arrowStartY} Q ${arrowStartX} ${arrowMidY} ${arrowEndX} ${arrowEndY}"
            fill="none" stroke="${MARK_COLOR}" stroke-width="3" marker-end="url(#arrowhead)" />
    `
    : "";

  const overlaySvg = Buffer.from(`
    <svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="arrowhead" markerWidth="10" markerHeight="10" refX="6" refY="5" orient="auto">
          <path d="M0,0 L10,5 L0,10 Z" fill="${MARK_COLOR}" />
        </marker>
      </defs>
      <ellipse cx="${targetCx}" cy="${targetCy}" rx="${ellipseRx}" ry="${ellipseRy}"
               fill="none" stroke="${MARK_COLOR}" stroke-width="3" stroke-dasharray="6,4" opacity="0.85" />
      <rect x="${rectX}" y="${rectY}" width="${rectW}" height="${rectH}"
            fill="none" stroke="${MARK_COLOR}" stroke-width="4" rx="6" />
      ${labelSvg}
      <circle cx="${badgeCx}" cy="${badgeCy}" r="15" fill="${MARK_COLOR}" />
      <text x="${badgeCx}" y="${badgeCy + 6}" font-family="sans-serif" font-size="17"
            font-weight="bold" fill="white" text-anchor="middle">1</text>
    </svg>
  `);

  await sharp(absPath)
    .composite([{ input: overlaySvg, top: 0, left: 0 }])
    .toFile(absPath + ".tmp");
  renameSync(absPath + ".tmp", absPath);

  return { fileName, absPath, widthPx: width, heightPx: height };
}

// ─────────────────────────────────────────────────────────────────────────
// Orquestación por vista: Antes (anotado) → ejecutar acción real → Después.
// ─────────────────────────────────────────────────────────────────────────

async function captureView(page: Page, view: ViewSpec, outDir: string): Promise<ViewResult> {
  await page.goto(`${BASE_URL}${view.href}`);
  await page.waitForLoadState("networkidle").catch(() => {});
  await page.waitForTimeout(500);

  const baseName = view.id.replace(/[^a-z0-9_-]/gi, "_");
  const images: CapturedImage[] = [];

  if (view.actions && view.actions.length > 0) {
    for (const [idx, action] of view.actions.entries()) {
      const n = idx + 1;
      const locator = await action.getLocator(page);
      const before = await captureAnnotated(
        page, locator, outDir, `${baseName}_paso${n}_antes.png`, action.description,
      );
      if (before) {
        images.push({ ...before, tag: `Paso ${n} — Antes`, stepExplanation: action.explanation });
      }

      try {
        await action.execute(page);
      } catch (err) {
        console.warn(`  Acción "${action.description}" en ${view.label} falló:`, (err as Error).message);
      }

      const afterFileName = `${baseName}_paso${n}_despues.png`;
      const after = await captureViewport(page, outDir, afterFileName);
      images.push({ ...after, tag: `Paso ${n} — Después`, stepExplanation: action.description });
    }
  } else {
    // Vista de solo lectura: una sola captura del primer viewport.
    const single = await captureViewport(page, outDir, `${baseName}.png`);
    images.push(single);
  }

  return { view, images };
}

// ─────────────────────────────────────────────────────────────────────────
// Página de leyenda: explica la notación usada en todo el documento.
// ─────────────────────────────────────────────────────────────────────────

function buildLegendSection(legendImagePath: string): Paragraph[] {
  return [
    new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun({ text: "Cómo leer este manual" })] }),
    new Paragraph({ children: [new TextRun({
      text: "Cada acción documentada muestra dos capturas: el estado \"Antes\" (con el control señalado) y el " +
        "estado \"Después\" (el resultado real tras ejecutar la acción). Las acciones de este manual se " +
        "ejecutaron de verdad sobre el sistema — los datos de prueba creados (marcados como \"Prueba manual\") " +
        "quedan visibles en el sistema real.",
    })] }),
    new Paragraph({
      alignment: AlignmentType.CENTER,
      children: [new ImageRun({
        type: "png",
        data: readFileSync(legendImagePath),
        transformation: { width: 420, height: 150 },
      })],
    }),
    new Paragraph({ children: [new TextRun({ text: "Círculo numerado: ", bold: true }),
      new TextRun({ text: "indica el orden del paso dentro de la vista, cuando hay más de una acción." })] }),
    new Paragraph({ children: [new TextRun({ text: "Recuadro rojo: ", bold: true }),
      new TextRun({ text: "señala con precisión el control (botón, interruptor o campo) sobre el que se ejecutó la acción en la captura \"Antes\"." })] }),
    new Paragraph({ children: [new TextRun({ text: "Óvalo punteado: ", bold: true }),
      new TextRun({ text: "resalta la zona alrededor del control para ubicarlo de un vistazo dentro de la pantalla completa." })] }),
    new Paragraph({ children: [new TextRun({ text: "Etiqueta con flecha: ", bold: true }),
      new TextRun({ text: "describe en una frase corta qué acción se realiza y apunta directamente al control correspondiente." })] }),
    new Paragraph({ children: [new TextRun({ text: "Captura \"Después\": ", bold: true }),
      new TextRun({ text: "muestra el resultado real inmediatamente después de ejecutar la acción (confirmación, fila nueva, cambio aplicado)." })] }),
    new Paragraph({ children: [new TextRun({ text: "Capturas sin marcar: ", bold: true }),
      new TextRun({ text: "corresponden a vistas de solo lectura, sin ninguna acción que ejecutar." })] }),
    new Paragraph({ text: "" }),
  ];
}

async function buildLegendImage(outDir: string): Promise<string> {
  const width = 420;
  const height = 150;
  const svg = Buffer.from(`
    <svg width="${width}" height="${height}" xmlns="http://www.w3.org/2000/svg">
      <defs>
        <marker id="legend-arrowhead" markerWidth="10" markerHeight="10" refX="6" refY="5" orient="auto">
          <path d="M0,0 L10,5 L0,10 Z" fill="${MARK_COLOR}" />
        </marker>
      </defs>
      <rect width="${width}" height="${height}" fill="#f8fafc" />

      <rect x="120" y="10" width="150" height="10" fill="${MARK_COLOR}" fill-opacity="0.92" rx="4" />
      <text x="195" y="18" font-family="sans-serif" font-size="9" font-weight="600" fill="white" text-anchor="middle">Haga clic aquí</text>
      <path d="M 195 20 Q 195 45 90 62" fill="none" stroke="${MARK_COLOR}" stroke-width="3" marker-end="url(#legend-arrowhead)" />

      <ellipse cx="70" cy="70" rx="46" ry="32" fill="none" stroke="${MARK_COLOR}" stroke-width="3" stroke-dasharray="6,4" opacity="0.85" />
      <rect x="35" y="55" width="70" height="30" fill="none" stroke="${MARK_COLOR}" stroke-width="4" rx="6" />
      <circle cx="29" cy="49" r="14" fill="${MARK_COLOR}" />
      <text x="29" y="54" font-family="sans-serif" font-size="15" font-weight="bold" fill="white" text-anchor="middle">1</text>
      <text x="70" y="110" font-family="sans-serif" font-size="12" fill="#334155" text-anchor="middle">Antes</text>

      <rect x="280" y="55" width="110" height="34" fill="#dcfce7" stroke="#16a34a" stroke-width="2" rx="6" />
      <text x="335" y="110" font-family="sans-serif" font-size="12" fill="#334155" text-anchor="middle">Después</text>
    </svg>
  `);
  const outPath = path.join(outDir, "_legend.png");
  await sharp(svg).png().toFile(outPath);
  return outPath;
}

// ─────────────────────────────────────────────────────────────────────────
// Documento Word por rol — tamaño de página fijo y espaciado explícito para
// que ninguna imagen quede cortada a mitad de página ni pegada al texto.
// ─────────────────────────────────────────────────────────────────────────

function scaledDimensions(widthPx: number, heightPx: number): { width: number; height: number } {
  let targetWidth = DOCX_IMAGE_WIDTH;
  let targetHeight = Math.round(heightPx * (targetWidth / widthPx));
  if (targetHeight > DOCX_IMAGE_MAX_HEIGHT) {
    const scale = DOCX_IMAGE_MAX_HEIGHT / targetHeight;
    targetHeight = DOCX_IMAGE_MAX_HEIGHT;
    targetWidth = Math.round(targetWidth * scale);
  }
  return { width: targetWidth, height: targetHeight };
}

async function buildDocx(roleSpec: RoleSpec, results: ViewResult[], legendImagePath: string, outPath: string) {
  const children: Paragraph[] = [
    new Paragraph({
      heading: HeadingLevel.TITLE,
      children: [new TextRun({ text: `Panel del chatbot — Rol ${roleSpec.displayName}` })],
    }),
    new Paragraph({ children: [new TextRun({ text: roleSpec.summary })], spacing: { after: 300 } }),
    ...buildLegendSection(legendImagePath),
  ];

  let lastSection = "";
  for (const { view, images } of results) {
    if (view.section !== lastSection) {
      children.push(new Paragraph({
        heading: HeadingLevel.HEADING_1,
        children: [new TextRun({ text: view.section })],
        spacing: { before: 400, after: 200 },
        pageBreakBefore: true,
      }));
      lastSection = view.section;
    }
    children.push(new Paragraph({
      heading: HeadingLevel.HEADING_2,
      children: [new TextRun({ text: view.label })],
      spacing: { before: 300, after: 100 },
    }));
    children.push(new Paragraph({
      children: [new TextRun({ text: view.description, italics: true })],
      spacing: { after: 200 },
    }));

    for (const image of images) {
      if (image.tag) {
        children.push(new Paragraph({
          children: [new TextRun({ text: image.tag, bold: true })],
          spacing: { before: 150, after: 80 },
        }));
      }
      if (image.stepExplanation) {
        children.push(new Paragraph({
          children: [new TextRun({ text: image.stepExplanation })],
          spacing: { after: 120 },
        }));
      }
      const { width, height } = scaledDimensions(image.widthPx, image.heightPx);
      children.push(new Paragraph({
        alignment: AlignmentType.CENTER,
        spacing: { after: 300 },
        children: [new ImageRun({
          type: "png",
          data: readFileSync(image.absPath),
          transformation: { width, height },
        })],
      }));
    }
  }

  const doc = new Document({
    sections: [{
      properties: {
        page: {
          size: { orientation: PageOrientation.PORTRAIT, width: 11906, height: 16838 }, // A4 en twentieths of a point
          margin: { top: 1440, bottom: 1440, left: 1440, right: 1440 }, // 1 pulgada
        },
      },
      children,
    }],
  });
  const buffer = await Packer.toBuffer(doc);
  writeFileSync(outPath, buffer);
}

// ─────────────────────────────────────────────────────────────────────────
// Main
// ─────────────────────────────────────────────────────────────────────────

async function run() {
  const browser = await chromium.launch();
  const readmeSections: string[] = ["# Vistas por rol\n",
    "Documento generado automáticamente — no editar a mano. Regenerar con " +
    "`npx tsx scripts/generate-role-docs.ts` tras cambios en el sidebar o los permisos. " +
    "Este script EJECUTA acciones reales (crea usuarios, documentos, roles, reglas y proveedores de prueba); " +
    "los datos creados quedan en el sistema. Ver también el documento Word por rol (`<rol>.docx`).\n"];

  mkdirSync(OUT_DIR, { recursive: true });
  const legendImagePath = await buildLegendImage(OUT_DIR);

  for (const roleSpec of ROLES) {
    const email = process.env[roleSpec.emailEnv];
    const password = process.env[roleSpec.passwordEnv];
    if (!email || !password) {
      console.warn(`Saltando rol ${roleSpec.role}: faltan ${roleSpec.emailEnv}/${roleSpec.passwordEnv}`);
      continue;
    }

    const roleDir = path.join(OUT_DIR, roleSpec.role);
    mkdirSync(roleDir, { recursive: true });

    const context = await browser.newContext({ viewport: VIEWPORT });
    const page = await context.newPage();
    // Diagnóstico: capturar cualquier error de React/JS del lado del cliente
    // (p. ej. el crash intermitente visto en Documentos) para ver el stack
    // real en la salida del script, en vez de solo la captura del error boundary.
    page.on("console", (msg) => {
      if (msg.type() === "error") console.error(`  [console.error][${roleSpec.role}]`, msg.text());
    });
    page.on("pageerror", (err) => {
      console.error(`  [pageerror][${roleSpec.role}]`, err.message, "\n", err.stack);
    });

    console.log(`Iniciando sesión como ${roleSpec.displayName}...`);
    await login(page, email, password);

    readmeSections.push(`\n## ${roleSpec.displayName}\n\n${roleSpec.summary}\n`);

    const results: ViewResult[] = [];
    let lastSection = "";
    for (const view of roleSpec.views) {
      console.log(`  Capturando ${roleSpec.role} → ${view.label} (${view.href})`);
      const result = await captureView(page, view, roleDir);
      results.push(result);

      if (view.section !== lastSection) {
        readmeSections.push(`\n### ${view.section}\n`);
        lastSection = view.section;
      }
      readmeSections.push(`\n**${view.label}**\n\n${view.description}\n`);
      for (const image of result.images) {
        if (image.tag) readmeSections.push(`\n_${image.tag}_\n`);
        if (image.stepExplanation) readmeSections.push(`\n${image.stepExplanation}\n`);
        readmeSections.push(`\n![${view.label} (${roleSpec.displayName})](./${roleSpec.role}/${image.fileName})\n`);
      }
    }

    await context.close();

    const docxPath = path.join(OUT_DIR, `${roleSpec.role}.docx`);
    console.log(`  Generando ${docxPath}...`);
    await buildDocx(roleSpec, results, legendImagePath, docxPath);
  }

  await browser.close();

  writeFileSync(path.join(OUT_DIR, "README.md"), readmeSections.join("\n"), "utf-8");
  console.log(`\nListo. README en ${path.join(OUT_DIR, "README.md")}, documentos Word en ${OUT_DIR}/<rol>.docx`);
}

run().catch((err) => {
  console.error(err);
  process.exit(1);
});
