/**
 * Chatbot Widget - Preact + Shadow DOM
 *
 * Atributos del script tag (auto-init):
 *   data-api-url="..."            - URL del backend
 *   data-api-key="..."            - API key del widget
 *   data-chatbot-name="..."       - nombre del bot
 *   data-greeting-message="..."  - mensaje de bienvenida
 *   data-open-on-load="true"      - abre el panel al cargar
 *   data-suggestions="a,b,c"     - sugerencias iniciales (CSV o JSON array)
 *   data-proactive-message="..."  - burbuja flotante sobre el launcher
 *   data-position="bottom-right"  - esquina del widget (valor inicial; se
 *                                    reemplaza por el de /widget/public/config
 *                                    en cuanto llega la respuesta)
 *   data-show-bot-icon="false"    - ocultar icono SVG del bot (idem, valor
 *                                    inicial hasta que llega la config real)
 *   data-launcher-label="..."     - etiqueta junto al launcher (opcional)
 *
 * API programática (window.UsoBot):
 *   open() / close() / toggle() / isOpen()
 *   showNewMessage(text) / startConversation(text)
 *   setContext(meta)
 *   on(event, fn) / off(event, fn)
 *   Eventos: 'open' | 'close' | 'message:sent' | 'message:received' | 'ready'
 */

import { render } from "preact";
import { useEffect, useRef, useState } from "preact/hooks";
import { marked } from "marked";
import DOMPurify from "dompurify";
import { streamChat, SERVICE_UNAVAILABLE_MESSAGE } from "./chat";
import type { SourceChunk, ChatHistoryMessage } from "./chat";
import { STYLES } from "./styles";

// Mitigación de reverse tabnabbing: todo <a target> recibe rel="noopener noreferrer nofollow".
DOMPurify.addHook("afterSanitizeAttributes", (node) => {
  if (node.tagName === "A" && node.hasAttribute("target")) {
    node.setAttribute("rel", "noopener noreferrer nofollow");
  }
});

type WidgetEvent = "open" | "close" | "message:sent" | "message:received" | "ready";
type WidgetEventHandler = (payload?: unknown) => void;

interface WidgetController {
  open(): void;
  close(): void;
  toggle(): void;
  isOpen(): boolean;
  showNewMessage(text: string): void;
  startConversation(text: string): void;
  setContext(meta: Record<string, unknown>): void;
  on(event: WidgetEvent, fn: WidgetEventHandler): void;
  off(event: WidgetEvent, fn: WidgetEventHandler): void;
}

declare global {
  interface Window { UsoBot?: WidgetController; __USOBOT__?: WidgetController }
}

const _listeners = new Map<WidgetEvent, Set<WidgetEventHandler>>();

function emit(event: WidgetEvent, payload?: unknown) {
  const set = _listeners.get(event);
  if (!set) return;
  set.forEach((fn) => { try { fn(payload); } catch { /* aísla errores del handler */ } });
}

let _bridge: {
  setOpen: (v: boolean) => void;
  isOpen: () => boolean;
  setInput: (v: string) => void;
  triggerSend: () => void;
  setContext: (meta: Record<string, unknown>) => void;
} | null = null;

function createController(): WidgetController {
  return {
    open()  { _bridge?.setOpen(true); },
    close() { _bridge?.setOpen(false); },
    toggle() { _bridge?.setOpen(!_bridge?.isOpen()); },
    isOpen() { return !!_bridge?.isOpen(); },
    showNewMessage(text: string) {
      _bridge?.setOpen(true);
      _bridge?.setInput(text);
    },
    startConversation(text: string) {
      _bridge?.setOpen(true);
      _bridge?.setInput(text);
      setTimeout(() => _bridge?.triggerSend(), 0);
    },
    setContext(meta: Record<string, unknown>) {
      _bridge?.setContext(meta);
    },
    on(event, fn) {
      let set = _listeners.get(event);
      if (!set) { set = new Set(); _listeners.set(event, set); }
      set.add(fn);
    },
    off(event, fn) {
      _listeners.get(event)?.delete(fn);
    },
  };
}

if (typeof window !== "undefined" && !window.__USOBOT__) {
  const ctrl = createController();
  window.__USOBOT__ = ctrl;
  // Alias para integraciones existentes que referencian window.UsoBot.
  Object.defineProperty(window, "UsoBot", { value: ctrl, writable: false, configurable: true });
}

// El renderer de marked es global y no recibe props, así que el origen del
// backend se guarda aquí: las rutas relativas de las imágenes apuntan a los
// archivos servidos por el backend, no al sitio que embebe el widget.
let _assetBase = "";
export function setAssetBase(url: string): void {
  _assetBase = (url || "").replace(/\/+$/, "");
}

marked.use({ breaks: true, gfm: true });
marked.use({
  renderer: {
    link({ href, text }: { href: string; title?: string | null; text: string }) {
      const isPdf = /\.pdf(\?.*)?$/i.test(href || "");
      const cls = isPdf ? ' class="pdf-link"' : "";
      return `<a href="${href}" target="_blank" rel="noopener noreferrer"${cls}>${text}</a>`;
    },
    image({ href, text }: { href: string; title?: string | null; text: string }) {
      const raw = href || "";
      let src: string;
      if (raw.startsWith("http") || raw.startsWith("data:")) {
        src = raw;
      } else if (raw.startsWith("/")) {
        src = `${_assetBase}${raw}`;
      } else {
        src = `${_assetBase}/uploads/${raw}`;
      }
      return `<img src="${src}" alt="${text || ""}" />`;
    },
  },
});

function BotIcon({ size = 16, logoUrl }: { size?: number; logoUrl?: string | null }) {
  if (logoUrl) {
    return (
      <img
        src={logoUrl}
        width={size}
        height={size}
        style={{ objectFit: "contain", borderRadius: "4px", display: "block" }}
        alt="Bot"
        aria-hidden="true"
      />
    );
  }
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
      aria-hidden="true"
    >
      <path d="M12 8V4H8" />
      <rect width="16" height="12" x="4" y="8" rx="2" />
      <path d="M2 14h2" />
      <path d="M20 14h2" />
      <path d="M15 13v2" />
      <path d="M9 13v2" />
    </svg>
  );
}

const STORAGE_VERSION = 1;
const MAX_PERSISTED_MESSAGES = 50;

interface PersistedHistory {
  v: number;
  messages: Message[];
  updatedAt: number;
  conversationId?: string | null;
  // Estado de la tarjeta de escalación pendiente: sin esto, cerrar o recargar
  // el widget mientras el formulario de contacto está abierto lo hace
  // desaparecer sin aviso, aunque el backend siga esperando el consentimiento.
  escalState?: "hidden" | "prompt" | "form";
  escalConvId?: string | null;
}
function _apiKeyFingerprint(apiKey: string): string {
  let h = 0;
  for (let i = 0; i < apiKey.length; i++) {
    h = (h * 31 + apiKey.charCodeAt(i)) | 0;
  }
  return Math.abs(h).toString(36);
}

function storageKey(apiUrl: string, apiKey: string): string {
  let host = "default";
  try { host = new URL(apiUrl).host || "default"; } catch { /* URL inválida */ }
  return `usobot:history:${host}:${_apiKeyFingerprint(apiKey)}`;
}

function loadHistory(apiUrl: string, apiKey: string): {
  messages: Message[];
  conversationId: string | null;
  escalState: "hidden" | "prompt" | "form";
  escalConvId: string | null;
} | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.localStorage.getItem(storageKey(apiUrl, apiKey));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as PersistedHistory;
    if (parsed.v !== STORAGE_VERSION || !Array.isArray(parsed.messages)) return null;
    return {
      messages: parsed.messages.map((m) => ({ ...m, streaming: false, error: false })),
      conversationId: parsed.conversationId ?? null,
      escalState: parsed.escalState ?? "hidden",
      escalConvId: parsed.escalConvId ?? null,
    };
  } catch { return null; }
}

function saveHistory(
  apiUrl: string, apiKey: string, messages: Message[], conversationId: string | null,
  escalState: "hidden" | "prompt" | "form" | "submitted" | "continue" | "error" = "hidden",
  escalConvId: string | null = null,
): void {
  if (typeof window === "undefined") return;
  try {
    const clean = messages
      .filter((m) => !m.streaming && !m.error && m.content.trim().length > 0)
      .slice(-MAX_PERSISTED_MESSAGES);
    // "submitted"/"continue"/"error" no son estados recuperables (son
    // transitorios de una sola interacción): se persisten como "hidden".
    const persistableEscalState = (escalState === "prompt" || escalState === "form") ? escalState : "hidden";
    const payload: PersistedHistory = {
      v: STORAGE_VERSION, messages: clean, updatedAt: Date.now(), conversationId,
      escalState: persistableEscalState, escalConvId: persistableEscalState === "hidden" ? null : escalConvId,
    };
    window.localStorage.setItem(storageKey(apiUrl, apiKey), JSON.stringify(payload));
  } catch { /* quota exceeded o incógnito - falla silenciosamente */ }
}

function clearHistory(apiUrl: string, apiKey: string): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(storageKey(apiUrl, apiKey)); } catch { /* ignore */ }
}

function getSessionId(apiUrl: string, apiKey: string): string {
  if (typeof window === "undefined") return "";
  const key = `${storageKey(apiUrl, apiKey)}:sid`;
  try {
    let sid = window.localStorage.getItem(key);
    if (!sid) {
      sid = (window.crypto?.randomUUID?.() ?? `sid-${Date.now()}-${Math.random().toString(36).slice(2)}`);
      window.localStorage.setItem(key, sid);
    }
    return sid;
  } catch {
    return `sid-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  }
}

function resetSessionId(apiUrl: string, apiKey: string): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.removeItem(`${storageKey(apiUrl, apiKey)}:sid`); } catch { /* ignore */ }
}

// Preferencias de accesibilidad - persistidas por navegador. Se guardan
// aparte del historial para que sobrevivan a "nueva conversación".
type TextScale = "sm" | "md" | "lg";
interface A11yPrefs { textScale: TextScale; highContrast: boolean; }
const A11Y_DEFAULTS: A11yPrefs = { textScale: "md", highContrast: false };

function a11yKey(apiUrl: string): string {
  let host = "default";
  try { host = new URL(apiUrl).host || "default"; } catch { /* URL inválida */ }
  return `usobot:history:${host}:a11y`;
}

function loadA11yPrefs(apiUrl: string): A11yPrefs {
  if (typeof window === "undefined") return { ...A11Y_DEFAULTS };
  try {
    const raw = window.localStorage.getItem(a11yKey(apiUrl));
    if (!raw) return { ...A11Y_DEFAULTS };
    const p = JSON.parse(raw) as Partial<A11yPrefs>;
    return {
      textScale: p.textScale === "sm" || p.textScale === "lg" ? p.textScale : "md",
      highContrast: !!p.highContrast,
    };
  } catch { return { ...A11Y_DEFAULTS }; }
}

function saveA11yPrefs(apiUrl: string, prefs: A11yPrefs): void {
  if (typeof window === "undefined") return;
  try { window.localStorage.setItem(a11yKey(apiUrl), JSON.stringify(prefs)); } catch { /* ignore */ }
}

interface Message {
  id: string;
  role: "user" | "assistant";
  content: string;
  sources?: SourceChunk[];
  streaming?: boolean;
  error?: boolean;
  backendId?: string;
}

interface WidgetSettings {
  show_sources: boolean;
  enable_copy_action: boolean;
  enable_feedback_icons: boolean;
  enable_tts: boolean;
  enable_accessibility: boolean;
  show_end_chat_button: boolean;
  show_new_chat_button: boolean;
  enable_csat: boolean;
  csat_question: string;
  csat_reasons: Record<string, string>;
  enable_escalation: boolean;
  max_input_chars: number;
}

let _id = 0;
const uid = () => String(++_id);

function MarkdownContent({ content, streaming }: { content: string; streaming?: boolean }) {
  if (streaming && !content) {
    return (
      <div class="md">
        <span class="typing-dots" aria-label="Escribiendo">
          <span /><span /><span />
        </span>
      </div>
    );
  }
  const raw = marked.parse(content || "") as string;
  const wrapped = raw.replace(/<table>/g, '<div class="table-wrap"><table>').replace(/<\/table>/g, '</table></div>');
  const html = DOMPurify.sanitize(wrapped, {
    ADD_TAGS: ["img"],
    ADD_ATTR: ["target", "src", "alt", "width", "height", "title"],
  });
  return (
    <div class="md">
      <span dangerouslySetInnerHTML={{ __html: html }} />
      {streaming && <span class="cursor">▋</span>}
    </div>
  );
}

function Sources({ sources }: { sources: SourceChunk[] }) {
  const [open, setOpen] = useState(false);
  if (!sources.length) return null;
  return (
    <div class="sources">
      <button class="sources-toggle" onClick={() => setOpen((o) => !o)}>
        {open ? "▲" : "▼"} {sources.length} fuente{sources.length !== 1 ? "s" : ""}
      </button>
      {open && (
        <ul class="sources-list">
          {sources.map((s, i) => (
            <li key={i} class="source-item">
              <div class="source-header">
                <span class="source-name">{s.source_name || "Fuente"}</span>
                <span class="source-score">{(s.score * 100).toFixed(0)}%</span>
              </div>
              <p class="source-text">{s.text}</p>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function MessageActions({ content, backendId, conversationId, apiUrl, apiKey, settings, ttsSupported, isSpeaking, onSpeak }: {
  content: string; backendId?: string; conversationId?: string | null; apiUrl: string; apiKey: string; settings: WidgetSettings;
  ttsSupported?: boolean; isSpeaking?: boolean; onSpeak?: () => void;
}) {
  const [copied, setCopied] = useState(false);
  const [feedback, setFeedback] = useState<"positive" | "negative" | null>(null);

  async function handleCopy() {
    try { await navigator.clipboard.writeText(content); } catch { /* ignore */ }
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  }

  async function handleFeedback(type: "positive" | "negative") {
    if (feedback === type) return;
    setFeedback(type);
    if (!backendId || !conversationId) return;
    try {
      await fetch(`${apiUrl}/api/v1/widget/public/messages/${backendId}/feedback`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json", "X-Widget-Key": apiKey },
        body: JSON.stringify({ feedback: type, conversation_id: conversationId }),
      });
    } catch { /* fire and forget */ }
  }

  if (!settings.enable_copy_action && !settings.enable_feedback_icons && !ttsSupported) return null;

  return (
    <div class="msg-actions">
      {ttsSupported && onSpeak && (
        <button class={`action-btn ${isSpeaking ? "action-active" : ""}`} onClick={onSpeak} title={isSpeaking ? "Detener lectura" : "Escuchar en voz alta"} aria-label={isSpeaking ? "Detener lectura" : "Escuchar en voz alta"}>
          {isSpeaking ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><rect x="6" y="5" width="4" height="14" rx="1"/><rect x="14" y="5" width="4" height="14" rx="1"/></svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><polygon points="11 5 6 9 2 9 2 15 6 15 11 19 11 5"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07M19.07 4.93a10 10 0 0 1 0 14.14"/></svg>
          )}
        </button>
      )}
      {settings.enable_copy_action && (
        <button class={`action-btn ${copied ? "action-active" : ""}`} onClick={handleCopy} title="Copiar">
          {copied ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14"><polyline points="20 6 9 17 4 12"/></svg>
          ) : (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>
          )}
        </button>
      )}
      {settings.enable_feedback_icons && (
        <>
          <button class={`action-btn ${feedback === "positive" ? "action-positive" : ""}`} onClick={() => handleFeedback("positive")} title="Útil">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M14 9V5a3 3 0 0 0-3-3l-4 9v11h11.28a2 2 0 0 0 2-1.7l1.38-9a2 2 0 0 0-2-2.3H14zM7 22H4a2 2 0 0 1-2-2v-7a2 2 0 0 1 2-2h3"/></svg>
          </button>
          <button class={`action-btn ${feedback === "negative" ? "action-negative" : ""}`} onClick={() => handleFeedback("negative")} title="No útil">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="14" height="14"><path d="M10 15v4a3 3 0 0 0 3 3l4-9V2H5.72a2 2 0 0 0-2 1.7l-1.38 9a2 2 0 0 0 2 2.3H10zM17 2h2.67A2.31 2.31 0 0 1 22 4v7a2.31 2.31 0 0 1-2.33 2H17"/></svg>
          </button>
        </>
      )}
    </div>
  );
}

type WidgetPosition = "bottom-right" | "bottom-left" | "top-right" | "top-left";

interface Props {
  apiUrl: string;
  apiKey: string;
  chatbotName: string;
  welcomeMessage: string;
  openOnLoad: boolean;
  suggestions: string[];
  proactiveMessage: string;
  position: WidgetPosition;
  showBotIcon: boolean;
  launcherLabel: string;
  applyPrimaryColor: (color: string) => void;
}

const DEFAULT_SETTINGS: WidgetSettings = {
  show_sources: true,
  enable_copy_action: true,
  enable_feedback_icons: true,
  enable_tts: true,
  enable_accessibility: true,
  show_end_chat_button: true,
  show_new_chat_button: true,
  enable_csat: false,
  csat_question: "¿Qué tan útil fue esta conversación?",
  csat_reasons: {},
  enable_escalation: true,
  max_input_chars: 4000,
};

function ChatWidget({
  apiUrl, apiKey, chatbotName, welcomeMessage, openOnLoad,
  suggestions: initialSuggestions, proactiveMessage: initialProactive,
  position: initialPosition, showBotIcon: initialShowBotIcon, launcherLabel,
  applyPrimaryColor,
}: Props) {

  const [suggestions, setSuggestions]           = useState<string[]>(initialSuggestions);
  const [proactiveMessage, setProactiveMessage] = useState<string>(initialProactive);
  const [showBotIcon, setShowBotIcon]           = useState<boolean>(initialShowBotIcon);
  const [position, setPosition]                 = useState<WidgetPosition>(initialPosition);
  const [logoUrl, setLogoUrl]                   = useState<string | null>(null);
  const [activeLauncherLabel, setLauncherLabel] = useState<string>(launcherLabel);
  const [activeChatbotName, setActiveChatbotName] = useState<string>(chatbotName);
  const [activeWelcome, setActiveWelcome]         = useState<string>(welcomeMessage);
  const [open, setOpen]                         = useState(openOnLoad);
  const [settings, setSettings]                 = useState<WidgetSettings>(DEFAULT_SETTINGS);
  const initialHistoryRef = useRef(loadHistory(apiUrl, apiKey));
  const [messages, setMessages]                 = useState<Message[]>(() => {
    const persisted = initialHistoryRef.current;
    if (persisted && persisted.messages.length > 0) return persisted.messages;
    return [{ id: uid(), role: "assistant", content: welcomeMessage }];
  });
  const [input, setInput]     = useState("");
  const [busy, setBusy]       = useState(false);

  // No se renderiza nada (ni la burbuja) hasta tener la config real: sin
  // esto, el widget aparecía primero con los valores por defecto del
  // script tag (posición, color, nombre "Asistente Virtual" genérico) y
  // luego "saltaba" a los reales en cuanto llegaba el fetch - visible como
  // un flash de la config equivocada, más notorio cuanto más difieran del
  // valor real configurado en el panel (posición y color, sobre todo).
  const [configReady, setConfigReady] = useState(false);
  // Badge: mensajes no leídos mientras el panel está cerrado
  const [unreadCount, setUnreadCount]     = useState(0);
  // Menú kebab (⋮) en el header
  const [kebabOpen, setKebabOpen]         = useState(false);
  // Modo offline: el backend no respondió al cargar
  const [offlineMode, setOfflineMode]     = useState(false);
  // CSAT: se activa cuando el usuario pulsa "Finalizar chat"
  const [conversationId, setConversationId] = useState<string | null>(
    () => initialHistoryRef.current?.conversationId ?? null,
  );
  const [csatState, setCsatState]           = useState<"hidden" | "pending" | "submitted">("hidden");
  const [csatScore, setCsatScore]           = useState<number | null>(null);
  const [csatComment, setCsatComment]       = useState("");
  const [csatReasons, setCsatReasons]       = useState<string[]>([]);
  // prompt: "¿hablar con un humano?" · form: contacto (correo/WhatsApp) · submitted: confirmación
  // continue: "¿continuar con el chatbot?" tras un "No" · error: falló el envío del contacto.
  // Se recupera de localStorage (ver saveHistory) para que cerrar o recargar
  // el widget con el formulario a medio llenar no lo haga desaparecer.
  const [escalState, setEscalState]         = useState<"hidden" | "prompt" | "form" | "submitted" | "continue" | "error">(
    () => initialHistoryRef.current?.escalState ?? "hidden",
  );
  const [escalSending, setEscalSending]     = useState(false);
  const [escalConvId, setEscalConvId]       = useState<string | null>(
    () => initialHistoryRef.current?.escalConvId ?? null,
  );
  const [escalType, setEscalType]           = useState<"email" | "whatsapp">("email");
  const [escalValue, setEscalValue]         = useState("");
  const [escalError, setEscalError]         = useState("");
  // Accesibilidad: tamaño de texto, alto contraste, y estado del sub-panel.
  const [a11y, setA11y]                     = useState<A11yPrefs>(() => loadA11yPrefs(apiUrl));
  const [a11yOpen, setA11yOpen]             = useState(false);
  // TTS: id del mensaje que se está leyendo en voz alta (o null).
  const [speakingId, setSpeakingId]         = useState<string | null>(null);

  // Refs
  const contextRef = useRef<Record<string, unknown>>({});
  const bottomRef  = useRef<HTMLDivElement>(null);
  const inputRef   = useRef<HTMLTextAreaElement>(null);
  const abortRef   = useRef<AbortController | null>(null);
  const openRef    = useRef(open);
  openRef.current  = open;
  const sendRef    = useRef<() => void>(() => {});
  const kebabRef   = useRef<HTMLDivElement>(null);

  useEffect(() => {
    _bridge = {
      setOpen,
      isOpen: () => openRef.current,
      setInput,
      triggerSend: () => sendRef.current(),
      setContext: (meta) => { contextRef.current = { ...contextRef.current, ...meta }; },
    };
    emit("ready");
    return () => { _bridge = null; };
  }, []);

  useEffect(() => { emit(open ? "open" : "close"); }, [open]);

  // Al abrir el panel: limpiar badge de no leídos
  useEffect(() => {
    if (open) setUnreadCount(0);
  }, [open]);

  // Con el panel a pantalla completa en móvil, el <body> de la página
  // anfitriona seguía siendo scrolleable detrás del panel (position:fixed
  // no lo bloquea por sí solo) - el navegador reservaba espacio para su
  // barra de scroll nativa sobre ese body, visible como una franja gris
  // vertical superpuesta al panel, que cubría en apariencia toda la
  // pantalla pero no en los px reales que el sistema operativo pintaba.
  useEffect(() => {
    if (!open) return;
    if (!window.matchMedia("(max-width: 480px)").matches) return;
    const body = document.body;
    const scrollY = window.scrollY;
    const prevOverflow = body.style.overflow;
    const prevPosition = body.style.position;
    const prevWidth = body.style.width;
    const prevTop = body.style.top;
    body.style.overflow = "hidden";
    body.style.position = "fixed";
    body.style.width = "100%";
    body.style.top = `-${scrollY}px`;
    return () => {
      body.style.overflow = prevOverflow;
      body.style.position = prevPosition;
      body.style.width = prevWidth;
      body.style.top = prevTop;
      window.scrollTo(0, scrollY);
    };
  }, [open]);

  // Cerrar kebab si se hace click fuera, o con Escape (navegación por teclado).
  // e.target de un evento disparado dentro del Shadow DOM llega "retargeted"
  // al host (<chatbot-widget>) cuando se escucha desde document - nunca es
  // un nodo real dentro del shadow, así que kebabRef.contains(e.target)
  // daba siempre false y cerraba el menú en cualquier click interno, antes
  // de que el onClick del botón llegara a disparar su acción (mousedown
  // ocurre antes que click). composedPath() sí resuelve el target real.
  useEffect(() => {
    if (!kebabOpen) return;
    function onOutsideClick(e: MouseEvent) {
      const path = e.composedPath();
      if (kebabRef.current && !path.includes(kebabRef.current)) {
        setKebabOpen(false);
      }
    }
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setKebabOpen(false);
    }
    document.addEventListener("mousedown", onOutsideClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onOutsideClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [kebabOpen]);

  // Cerrar panel de accesibilidad con Escape (solo tenía el botón "×" interno)
  useEffect(() => {
    if (!a11yOpen) return;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") setA11yOpen(false);
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [a11yOpen]);

  // retryTick permite reintentar la carga de config sin recargar la página (botón "Reintentar" del panel offline).
  const [retryTick, setRetryTick] = useState(0);
  useEffect(() => { setAssetBase(apiUrl); }, [apiUrl]);

  useEffect(() => {
    let cancelled = false;
    fetch(`${apiUrl}/api/v1/widget/public/config`, {
      headers: apiKey ? { "X-Widget-Key": apiKey } : {},
    })
      .then((r) => {
        // Los errores del backend traen cuerpo JSON, así que sin este control
        // r.json() no lanza: el widget se daría por conectado y aplicaría los
        // valores por defecto en vez de la configuración real.
        if (!r.ok) throw new Error(`config ${r.status}`);
        return r.json();
      })
      .then((data) => {
        if (cancelled) return;
        setOfflineMode(false);
        setSettings({
          show_sources:          data.show_sources          ?? true,
          enable_copy_action:    data.enable_copy_action    ?? true,
          enable_feedback_icons: data.enable_feedback_icons ?? true,
          enable_tts:            data.enable_tts            ?? true,
          enable_accessibility:  data.enable_accessibility  ?? true,
          show_end_chat_button:  data.show_end_chat_button  ?? true,
          show_new_chat_button:  data.show_new_chat_button  ?? true,
          enable_csat:           data.enable_csat           ?? false,
          csat_question:         data.csat_question         ?? DEFAULT_SETTINGS.csat_question,
          csat_reasons:          data.csat_reasons          ?? {},
          enable_escalation:     data.enable_escalation     ?? true,
          max_input_chars:       data.max_input_chars       ?? DEFAULT_SETTINGS.max_input_chars,
        });
        if (typeof data.show_bot_icon === "boolean") setShowBotIcon(data.show_bot_icon);
        if (typeof data.position === "string") setPosition(parsePosition(data.position));
        if (Array.isArray(data.suggestions))          setSuggestions(data.suggestions);
        if (typeof data.proactive_message === "string") setProactiveMessage(data.proactive_message);
        if (typeof data.logo_url === "string" && data.logo_url) setLogoUrl(data.logo_url);
        if (typeof data.primary_color === "string" && data.primary_color) {
          applyPrimaryColor(data.primary_color);
        }
        if (typeof data.launcher_label === "string") setLauncherLabel(data.launcher_label);
        if (typeof data.chatbot_name === "string" && data.chatbot_name) {
          setActiveChatbotName(data.chatbot_name);
        }
        if (typeof data.welcome_message === "string" && data.welcome_message) {
          setActiveWelcome(data.welcome_message);
          setMessages((prev) => {
            if (prev.length === 1 && prev[0].role === "assistant" && prev[0].content === welcomeMessage) {
              return [{ ...prev[0], content: data.welcome_message }];
            }
            return prev;
          });
        }
        setConfigReady(true);
      })
      .catch(() => {
        if (cancelled) return;
        setOfflineMode(true);
        // Aunque falló, ya no queda nada más que esperar: hay que mostrar
        // el panel offline en vez de ocultar el widget indefinidamente.
        setConfigReady(true);
      });
    return () => { cancelled = true; };
  }, [apiUrl, apiKey, retryTick]);

  const prevBusyRef = useRef(false);
  useEffect(() => {
    const justFinished = prevBusyRef.current && !busy;
    prevBusyRef.current = busy;
    if (!busy || justFinished) {
      bottomRef.current?.scrollIntoView({ behavior: "smooth" });
    }
  }, [messages, busy]);

  // Persistir historial (incluye conversationId y la tarjeta de escalación
  // pendiente - ver PersistedHistory)
  useEffect(() => {
    saveHistory(apiUrl, apiKey, messages, conversationId, escalState, escalConvId);
  }, [messages, apiUrl, apiKey, conversationId, escalState, escalConvId]);

  // Focus al abrir
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 50);
  }, [open]);

  function handleMinimize() {
    setOpen(false);
  }

  function handleEndChat() {
    setKebabOpen(false);
    if (escalState === "prompt" || escalState === "form") setEscalState("hidden");
    if (settings.enable_csat && conversationId && csatState === "hidden") {
      setCsatState("pending");
    } else {
      setOpen(false);
    }
  }

  // Nueva conversación: cancela el request activo y resetea todo.
  function handleClearConversation() {
    abortRef.current?.abort();
    abortRef.current = null;
    clearHistory(apiUrl, apiKey);
    resetSessionId(apiUrl, apiKey);
    setMessages([{ id: uid(), role: "assistant", content: activeWelcome }]);
    setBusy(false);
    setCsatState("hidden");
    setCsatScore(null);
    setCsatComment("");
    setCsatReasons([]);
    setConversationId(null);
    setEscalState("hidden");
    setEscalConvId(null);
    setEscalValue("");
    setKebabOpen(false);
  }

  function handleCsatStarClick(score: number) {
    setCsatScore(score);
  }

  async function handleCsatSubmit() {
    if (!csatScore) return;
    setCsatState("submitted");
    if (!conversationId) return;
    const comment = csatComment.trim() || undefined;
    try {
      await fetch(`${apiUrl}/api/v1/widget/public/csat`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Widget-Key": apiKey },
        body: JSON.stringify({
          conversation_id: conversationId,
          score: csatScore,
          ...(comment ? { comment } : {}),
          ...(csatReasons.length ? { reasons: csatReasons } : {}),
        }),
      });
    } catch { /* fire and forget */ }
  }

  // Persistir preferencias de accesibilidad cuando cambian.
  useEffect(() => { saveA11yPrefs(apiUrl, a11y); }, [a11y, apiUrl]);

  // Detener la lectura en voz alta al desmontar o cerrar el panel.
  useEffect(() => {
    if (!open) {
      try { window.speechSynthesis?.cancel(); } catch { /* noop */ }
      setSpeakingId(null);
    }
  }, [open]);

  function setTextScale(scale: TextScale) {
    setA11y((p) => ({ ...p, textScale: scale }));
  }
  function toggleContrast() {
    setA11y((p) => ({ ...p, highContrast: !p.highContrast }));
  }

  // Lee/detiene un mensaje del bot con la síntesis de voz nativa del
  // navegador. Sin dependencias externas; falla en silencio si no existe.
  function speakMessage(id: string, text: string) {
    try {
      const synth = window.speechSynthesis;
      if (!synth) return;
      if (speakingId === id) { synth.cancel(); setSpeakingId(null); return; }
      synth.cancel();
      // Quita marcas de markdown básicas para que no las lea literalmente.
      const clean = text.replace(/[*_`#>]/g, "").replace(/\[(.*?)\]\(.*?\)/g, "$1");
      const utter = new SpeechSynthesisUtterance(clean);
      utter.lang = "es-ES";
      utter.onend = () => setSpeakingId(null);
      utter.onerror = () => setSpeakingId(null);
      setSpeakingId(id);
      synth.speak(utter);
    } catch { setSpeakingId(null); }
  }
  const ttsSupported =
    typeof window !== "undefined" && !!window.speechSynthesis
    && settings.enable_tts !== false && settings.enable_accessibility !== false;

  function closeWithCsat() {
    if (settings.enable_csat && conversationId && csatState === "hidden") {
      setEscalState("hidden");
      setCsatState("pending");
    } else {
      setOpen(false);
    }
  }

  function validateContact(type: "email" | "whatsapp", value: string): string {
    const v = value.trim();
    if (!v) return type === "email" ? "Ingrese su correo electrónico." : "Ingrese su número de WhatsApp.";
    if (type === "email") {
      // Validación de correo pragmática (no RFC completo, pero atrapa errores comunes).
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v)) return "Ingrese un correo electrónico válido.";
    } else {
      // WhatsApp: 8 a 15 dígitos, admite +, espacios y guiones como separadores.
      const digits = v.replace(/[\s\-()]/g, "");
      if (!/^\+?\d{8,15}$/.test(digits)) return "Ingrese un número de WhatsApp válido (8 a 15 dígitos).";
    }
    return "";
  }

  async function handleEscalationSubmit() {
    if (escalSending) return;
    const val = escalValue.trim();
    const err = validateContact(escalType, val);
    if (err) { setEscalError(err); return; }
    if (!escalConvId) {
      setEscalError("Escriba primero su consulta para poder contactarle.");
      return;
    }
    setEscalError("");
    setEscalSending(true);
    try {
      const resp = await fetch(`${apiUrl}/api/v1/widget/public/escalation/contact`, {
        method: "POST",
        headers: { "Content-Type": "application/json", "X-Widget-Key": apiKey },
        body: JSON.stringify({
          conversation_id: escalConvId,
          contact_type: escalType,
          contact_value: val,
        }),
      });
      if (!resp.ok) {
        setEscalState("error");
        return;
      }
      setEscalState("submitted");
      setTimeout(() => { closeWithCsat(); }, 2200);
    } catch {
      setEscalState("error");
    } finally {
      setEscalSending(false);
    }
  }

  async function handleSend() {
    const q = input.trim();
    if (!q || busy || offlineMode) return;
    setInput("");

    const userMsg: Message    = { id: uid(), role: "user", content: q };
    const assistantId         = uid();
    const assistantMsg: Message = { id: assistantId, role: "assistant", content: "", streaming: true };

    const history: ChatHistoryMessage[] = messages
      .filter((m) => !m.streaming && !m.error && m.content)
      .slice(-10)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, userMsg, assistantMsg]);
    setBusy(true);
    emit("message:sent", { text: q, context: contextRef.current });

    const abort = new AbortController();
    abortRef.current = abort;

    // "Nueva conversación" limpia abortRef, así que si ya no apunta a esta
    // petición sus respuestas pertenecen a una conversación abandonada y no
    // deben tocar el estado actual.
    const isCurrent = () => abortRef.current === abort;

    await streamChat(
      apiUrl, q, null,
      {
        onSources(sources) {
          if (!isCurrent()) return;
          setMessages((prev) =>
            prev.map((m) => (m.id === assistantId ? { ...m, sources } : m)),
          );
        },
        onToken(token) {
          if (!isCurrent()) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId ? { ...m, content: m.content + token } : m,
            ),
          );
        },
        onDone(messageId, convId, escalationPrompt) {
          if (!isCurrent()) return;
          let finalText = "";
          setMessages((prev) => {
            const updated = prev.map((m) =>
              m.id === assistantId ? { ...m, streaming: false, backendId: messageId } : m,
            );
            finalText = updated.find((m) => m.id === assistantId)?.content ?? "";
            return updated;
          });
          setBusy(false);
          abortRef.current = null;
          emit("message:received", { text: finalText, messageId });
          if (convId) setConversationId(convId);
          // Mostrar prompt de escalamiento si el backend lo solicita
          if (escalationPrompt && convId) {
            setEscalConvId(convId);
            setEscalState("prompt");
          }
          // Badge: si el panel está cerrado, incrementar no leídos
          if (!openRef.current) setUnreadCount((n) => n + 1);
        },
        onError(msg) {
          if (!isCurrent()) return;
          setMessages((prev) =>
            prev.map((m) =>
              m.id === assistantId
                ? { ...m, content: msg, streaming: false, error: true }
                : m,
            ),
          );
          setBusy(false);
          abortRef.current = null;
        },
      },
      abort.signal, history, apiKey, getSessionId(apiUrl, apiKey),
    );
  }

  sendRef.current = handleSend;

  function handleKeyDown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  }

  function handleInput(e: Event) {
    const ta = e.target as HTMLTextAreaElement;
    setInput(ta.value);
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 120) + "px";
  }

  // El kebab solo aparece si tiene al menos un ítem que mostrar: alguna
  // acción de conversación habilitada, o el menú de accesibilidad.
  const hasKebabActions =
    (settings.show_new_chat_button && messages.length > 1)
    || settings.enable_accessibility !== false
    || settings.show_end_chat_button;

  // Nada se renderiza (ni la burbuja) hasta tener la config real - ver el
  // comentario en la declaración de configReady más arriba.
  if (!configReady) return null;

  return (
    <div class="root" data-position={position}>

      {/* ── Panel ── */}
      <div
        class={`panel ${open ? "panel-open" : ""}`}
        aria-hidden={!open}
        data-text-scale={a11y.textScale}
        data-contrast={a11y.highContrast ? "high" : "normal"}
      >

        {/* Header */}
        <div class="header">
          {showBotIcon && (
            <div class="header-avatar">
              <BotIcon size={18} logoUrl={logoUrl} />
            </div>
          )}
          <div class="header-info">
            <span class="header-name">{activeChatbotName}</span>
            <span class="header-status">
              {offlineMode ? "Sin conexión" : busy ? "Escribiendo…" : "En línea"}
            </span>
          </div>

          {/* Menú kebab (⋮) - agrupa "Nueva conversación" y "Finalizar chat" */}
          {hasKebabActions && (
            <div class="kebab-wrapper" ref={kebabRef}>
              <button
                class="header-btn"
                onClick={() => setKebabOpen((v) => !v)}
                aria-label="Más opciones"
                title="Más opciones"
                aria-expanded={kebabOpen}
                aria-haspopup="menu"
              >
                <svg viewBox="0 0 24 24" fill="currentColor" width="20" height="20">
                  <circle cx="12" cy="5"  r="1.7" />
                  <circle cx="12" cy="12" r="1.7" />
                  <circle cx="12" cy="19" r="1.7" />
                </svg>
              </button>
              {kebabOpen && (
                <div class="kebab-menu" role="menu">
                  {settings.show_new_chat_button && messages.length > 1 && (
                    <button class="kebab-item" role="menuitem" onClick={handleClearConversation}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
                        <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                        <path d="M3 3v5h5" />
                      </svg>
                      Nueva conversación
                    </button>
                  )}
                  {settings.enable_accessibility !== false && (
                    <button class="kebab-item" role="menuitem" onClick={() => { setA11yOpen(true); setKebabOpen(false); }}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
                        <circle cx="16" cy="4" r="1" />
                        <path d="m18 19 1-7-6 1" />
                        <path d="m5 8 3-3 5.5 3-2.36 3.5" />
                        <path d="M4.24 14.5a5 5 0 0 0 6.88 6" />
                        <path d="M13.76 17.5a5 5 0 0 0-6.88-6" />
                      </svg>
                      Accesibilidad
                    </button>
                  )}
                  {settings.show_end_chat_button && (
                    <button class="kebab-item kebab-item-end" role="menuitem" onClick={handleEndChat}>
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="16" height="16">
                        <path d="m16 17 5-5-5-5" />
                        <path d="M21 12H9" />
                        <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
                      </svg>
                      Finalizar chat
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {/* Botón cerrar (✕) - oculta el panel sin destruir la conversación */}
          <button
            class="close-btn"
            onClick={handleMinimize}
            aria-label="Cerrar"
            title="Cerrar"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="20" height="20">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Sub-panel de accesibilidad */}
        {a11yOpen && (
          <div class="a11y-panel" role="region" aria-label="Opciones de accesibilidad">
            <div class="a11y-panel-head">
              <span class="a11y-panel-title">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="14" height="14">
                  <circle cx="16" cy="4" r="1" />
                  <path d="m18 19 1-7-6 1" />
                  <path d="m5 8 3-3 5.5 3-2.36 3.5" />
                  <path d="M4.24 14.5a5 5 0 0 0 6.88 6" />
                  <path d="M13.76 17.5a5 5 0 0 0-6.88-6" />
                </svg>
                Accesibilidad
              </span>
              <button class="a11y-close" onClick={() => setA11yOpen(false)} aria-label="Cerrar accesibilidad" title="Cerrar">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="14" height="14">
                  <line x1="18" y1="6" x2="6" y2="18" /><line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              </button>
            </div>
            {/* Tamaño de texto */}
            <div class="a11y-row">
              <span class="a11y-label">Tamaño del texto</span>
              {/* radiogroup/radio + aria-checked, no aria-pressed: es una
                  selección única entre opciones excluyentes, no un botón de
                  encendido/apagado (WAI-ARIA APG, patrón Radio Group). */}
              <div class="a11y-scale" role="radiogroup" aria-label="Tamaño del texto">
                {(["sm", "md", "lg"] as TextScale[]).map((s, i) => (
                  <button
                    key={s}
                    class={`a11y-scale-btn ${a11y.textScale === s ? "a11y-scale-active" : ""}`}
                    onClick={() => setTextScale(s)}
                    role="radio"
                    aria-checked={a11y.textScale === s}
                    aria-label={["Texto pequeño", "Texto normal", "Texto grande"][i]}
                    style={{ fontSize: [12, 14, 17][i] + "px" }}
                  >A</button>
                ))}
              </div>
            </div>
            {/* Alto contraste */}
            <div class="a11y-row">
              <span class="a11y-label">Alto contraste</span>
              <button
                class={`a11y-toggle ${a11y.highContrast ? "a11y-toggle-on" : ""}`}
                onClick={toggleContrast}
                role="switch"
                aria-checked={a11y.highContrast}
                aria-label="Alto contraste"
              >
                <span class="a11y-toggle-knob" />
              </button>
            </div>
            {ttsSupported && (
              <p class="a11y-hint">
                Use el botón
                <svg class="a11y-hint-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" width="12" height="12">
                  <path d="M11 4.702a.705.705 0 0 0-1.203-.498L6.413 7.587A1.4 1.4 0 0 1 5.416 8H3a1 1 0 0 0-1 1v6a1 1 0 0 0 1 1h2.416a1.4 1.4 0 0 1 .997.413l3.383 3.384A.705.705 0 0 0 11 19.298z" />
                  <path d="M16 9a5 5 0 0 1 0 6" />
                  <path d="M19.364 18.364a9 9 0 0 0 0-12.728" />
                </svg>
                {" en cada respuesta para escucharla en voz alta."}
              </p>
            )}
          </div>
        )}

        {/* Modo offline */}
        {offlineMode ? (
          <div class="offline-panel">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="36" height="36" style={{ opacity: 0.35 }}>
              <line x1="1" y1="1" x2="23" y2="23" />
              <path d="M16.72 11.06A10.94 10.94 0 0 1 19 12.55" />
              <path d="M5 12.55a10.94 10.94 0 0 1 5.17-2.39" />
              <path d="M10.71 5.05A16 16 0 0 1 22.56 9" />
              <path d="M1.42 9a15.91 15.91 0 0 1 4.7-2.88" />
              <path d="M8.53 16.11a6 6 0 0 1 6.95 0" />
              <circle cx="12" cy="20" r="1" fill="currentColor" />
            </svg>
            <p class="offline-title">Sin conexión</p>
            <p class="offline-desc">{SERVICE_UNAVAILABLE_MESSAGE}</p>
            <button
              type="button"
              class="offline-retry-btn"
              onClick={() => setRetryTick((t) => t + 1)}
            >
              Reintentar
            </button>
          </div>
        ) : settings.enable_csat && csatState !== "hidden" ? (
          /* CSAT ocupa el cuerpo completo del panel (mismo espacio que
             mensajes + input) en vez de aparecer como una franja al fondo
             del scroll, donde competía por atención con el historial y el
             usuario podía seguir escribiendo mientras calificaba. */
          <div class="csat-fullscreen">
            {csatState === "pending" && (
              <div class="csat-panel" role="group" aria-label="Valoración de la conversación">
                <p class="csat-question">{settings.csat_question}</p>
                <div class="csat-stars">
                  {[1, 2, 3, 4, 5].map((n) => (
                    <button
                      key={n}
                      class={`csat-star ${n <= (csatScore ?? 0) ? "csat-star-filled" : ""}`}
                      onClick={() => handleCsatStarClick(n)}
                      aria-label={`${n} estrella${n !== 1 ? "s" : ""}`}
                      title={["", "Muy malo", "Malo", "Regular", "Bueno", "Excelente"][n]}
                    >★</button>
                  ))}
                </div>
                <div class="csat-star-labels">
                  <span>Muy disconforme</span>
                  <span>Muy conforme</span>
                </div>
                {Object.keys(settings.csat_reasons).length > 0 && (
                  <div class="csat-reasons" role="group" aria-label="Motivo de la calificación">
                    {Object.entries(settings.csat_reasons).map(([key, label]) => (
                      <label key={key} class={`csat-reason-item ${csatReasons.includes(key) ? "csat-reason-item-checked" : ""}`}>
                        <input
                          type="checkbox"
                          checked={csatReasons.includes(key)}
                          onChange={() => setCsatReasons((prev) =>
                            prev.includes(key) ? prev.filter((r) => r !== key) : [...prev, key]
                          )}
                        />
                        {label}
                      </label>
                    ))}
                  </div>
                )}
                <textarea
                  class="csat-comment"
                  placeholder="Cuéntenos su experiencia (opcional)…"
                  maxLength={300}
                  value={csatComment}
                  onInput={(e) => setCsatComment((e.target as HTMLTextAreaElement).value)}
                  rows={2}
                />
                <div class="csat-actions">
                  <button class="csat-skip" onClick={() => setCsatState("submitted")}>Omitir</button>
                  <button
                    class="csat-submit-btn"
                    onClick={handleCsatSubmit}
                    disabled={!csatScore}
                  >Finalizar</button>
                </div>
              </div>
            )}
            {csatState === "submitted" && (
              <div class="csat-thanks-wrap">
                <div class="csat-thanks-icon" aria-hidden="true">
                  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="26" height="26">
                    <circle cx="12" cy="12" r="10" />
                    <polyline points="8 12.5 10.8 15.5 16 9" />
                  </svg>
                </div>
                <div class="csat-thanks">¡Muchas gracias!</div>
                <div class="csat-thanks-actions">
                  {settings.show_new_chat_button && messages.length > 1 && (
                    <button class="csat-thanks-btn" onClick={handleClearConversation}>
                      Nueva conversación
                    </button>
                  )}
                  <button class="csat-thanks-btn" onClick={handleMinimize}>
                    Cerrar
                  </button>
                </div>
              </div>
            )}
          </div>
        ) : (
          <>
            {/* Mensajes */}
            <div class="messages" role="log" aria-live="polite">
              {messages.map((msg) => (
                <div key={msg.id} class={`msg-row msg-row-${msg.role}`}>
                  {msg.role === "assistant" && showBotIcon && (
                    <div class="msg-avatar" aria-hidden="true">
                      <BotIcon size={14} logoUrl={logoUrl} />
                    </div>
                  )}
                  <div class={`msg msg-${msg.role}`}>
                    {msg.role === "user" ? (
                      <span class="user-text">{msg.content}</span>
                    ) : (
                      <>
                        <MarkdownContent content={msg.content} streaming={msg.streaming} />
                        {settings.show_sources && msg.sources && <Sources sources={msg.sources} />}
                        {!msg.streaming && !msg.error && msg.content && (
                          <MessageActions
                            content={msg.content}
                            backendId={msg.backendId}
                            conversationId={conversationId}
                            apiUrl={apiUrl}
                            apiKey={apiKey}
                            settings={settings}
                            ttsSupported={ttsSupported}
                            isSpeaking={speakingId === msg.id}
                            onSpeak={() => speakMessage(msg.id, msg.content)}
                          />
                        )}
                      </>
                    )}
                  </div>
                </div>
              ))}

              {/* Tarjeta de contacto - aparece como burbuja del bot en el flujo */}
              {escalState !== "hidden" && (
                <div class="msg-row msg-row-assistant">
                  {showBotIcon && (
                    <div class="msg-avatar" aria-hidden="true">
                      <BotIcon size={14} logoUrl={logoUrl} />
                    </div>
                  )}
                  <div class={`msg msg-assistant escal-card${escalState === "submitted" ? " escal-card-done" : ""}`}>
                    {escalState === "prompt" && (
                      <>
                        <p class="escal-question">
                          ¿Desea que la universidad se ponga en contacto con usted?
                        </p>
                        <div class="escal-btn-row">
                          <button class="escal-yes-btn" onClick={() => setEscalState("form")}>
                            Sí
                          </button>
                          <button class="escal-no-btn" onClick={() => setEscalState("continue")}>
                            No
                          </button>
                        </div>
                      </>
                    )}
                    {escalState === "continue" && (
                      <>
                        <p class="escal-question">
                          ¿Desea continuar con el asistente virtual?
                        </p>
                        <div class="escal-btn-row">
                          <button class="escal-yes-btn" onClick={() => setEscalState("hidden")}>
                            Sí, continuar
                          </button>
                          <button
                            class="escal-no-btn"
                            onClick={() => { setEscalState("hidden"); closeWithCsat(); }}
                          >
                            No, finalizar
                          </button>
                        </div>
                      </>
                    )}
                    {escalState === "form" && (
                      <form
                        onSubmit={(e) => { e.preventDefault(); handleEscalationSubmit(); }}
                        noValidate
                      >
                        <p class="escal-question" id="escal-form-title">¿Cómo prefiere que lo contactemos?</p>
                        <div class="escal-type-row" role="radiogroup" aria-labelledby="escal-form-title">
                          <label class="escal-radio-label">
                            <input
                              type="radio"
                              name="escal-type"
                              value="email"
                              checked={escalType === "email"}
                              onChange={() => { setEscalType("email"); setEscalValue(""); setEscalError(""); }}
                            />
                            Correo electrónico
                          </label>
                          <label class="escal-radio-label">
                            <input
                              type="radio"
                              name="escal-type"
                              value="whatsapp"
                              checked={escalType === "whatsapp"}
                              onChange={() => { setEscalType("whatsapp"); setEscalValue(""); setEscalError(""); }}
                            />
                            WhatsApp
                          </label>
                        </div>
                        <label class="escal-input-label" for="escal-contact-input">
                          {escalType === "email" ? "Su correo electrónico" : "Su número de WhatsApp"}
                        </label>
                        <input
                          id="escal-contact-input"
                          type={escalType === "email" ? "email" : "tel"}
                          inputMode={escalType === "email" ? "email" : "tel"}
                          autoComplete={escalType === "email" ? "email" : "tel"}
                          class="escal-input"
                          placeholder={escalType === "email" ? "tucorreo@ejemplo.com" : "+503 7777 7777"}
                          value={escalValue}
                          onInput={(e) => { setEscalValue((e.target as HTMLInputElement).value); if (escalError) setEscalError(""); }}
                          maxLength={200}
                          aria-invalid={escalError ? "true" : "false"}
                          aria-describedby={escalError ? "escal-error" : undefined}
                          autoFocus
                        />
                        {escalError && (
                          <p class="escal-error" id="escal-error" role="alert">{escalError}</p>
                        )}
                        <div class="escal-form-actions">
                          <button type="button" class="escal-cancel-btn" onClick={() => { setEscalState("hidden"); setEscalError(""); }}>
                            Cancelar
                          </button>
                          <button type="submit" class="escal-submit-btn" disabled={escalSending}>
                            {escalSending ? "Enviando…" : "Enviar"}
                          </button>
                        </div>
                      </form>
                    )}
                    {escalState === "submitted" && (
                      <p class="escal-done">
                        ✓ Listo. La universidad se pondrá en contacto con usted pronto.
                      </p>
                    )}
                    {escalState === "error" && (
                      <>
                        <p class="escal-error" role="alert">
                          No se pudo enviar su solicitud. Intente de nuevo.
                        </p>
                        <div class="escal-btn-row">
                          <button class="escal-yes-btn" onClick={() => setEscalState("form")}>
                            Reintentar
                          </button>
                        </div>
                      </>
                    )}
                  </div>
                </div>
              )}

              <div ref={bottomRef} />
            </div>

            {/* Sugerencias iniciales */}
            {messages.length === 1 && messages[0].role === "assistant" && suggestions.length > 0 && !busy && (
              <div class="suggestions" role="group" aria-label="Sugerencias">
                {suggestions.map((s) => (
                  <button
                    key={s}
                    type="button"
                    class="suggestion-btn"
                    onClick={() => {
                      setInput(s);
                      setTimeout(() => sendRef.current(), 0);
                    }}
                  >
                    {s}
                  </button>
                ))}
              </div>
            )}

          </>
        )}

        {/* Input - oculto durante CSAT: el usuario está calificando/cerrando
            la conversación, no debería poder seguir escribiendo mensajes. */}
        {!(settings.enable_csat && csatState !== "hidden") && (
        <div class="input-row">
          <textarea
            ref={inputRef}
            class="input"
            placeholder={offlineMode ? "Servicio no disponible" : "Escribe un mensaje…"}
            value={input}
            onInput={handleInput}
            onKeyDown={handleKeyDown}
            rows={1}
            maxLength={settings.max_input_chars}
            disabled={busy || offlineMode}
            aria-label="Pregunta"
          />
          <button
            class="send-btn"
            onClick={handleSend}
            disabled={busy || !input.trim() || offlineMode}
            aria-label="Enviar"
          >
            {busy ? (
              <span class="spinner" />
            ) : (
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="16" height="16">
                <line x1="22" y1="2" x2="11" y2="13" />
                <polygon points="22 2 15 22 11 13 2 9 22 2" />
              </svg>
            )}
          </button>
        </div>
        )}
      </div>

      {/* ── Mensaje proactivo (sobre el launcher cerrado) ── */}
      {!open && proactiveMessage && (
        <div class="proactive-bubble" onClick={() => setOpen(true)} role="button" tabIndex={0}>
          <span class="proactive-text">{proactiveMessage}</span>
        </div>
      )}

      {/* ── Launcher label (etiqueta junto al botón) ── */}
      {!open && activeLauncherLabel && (
        <div class="launcher-label-wrap" onClick={() => setOpen(true)} role="button" tabIndex={0}>
          <span class="launcher-label-text">{activeLauncherLabel}</span>
        </div>
      )}

      {/* ── Bubble (launcher) ── */}
      <div class={`bubble-wrap${open ? " bubble-wrap-panel-open" : ""}`}>
        <button
          class="bubble"
          onClick={() => (open ? handleMinimize() : setOpen(true))}
          aria-label={open ? "Minimizar chat" : "Abrir chat"}
          aria-expanded={open}
        >
          {open ? (
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" width="20" height="20">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          ) : logoUrl ? (
            <img
              src={logoUrl}
              width={28}
              height={28}
              style={{ objectFit: "cover", borderRadius: "50%", display: "block" }}
              alt=""
              aria-hidden="true"
            />
          ) : (
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
              <path d="M12 8V4H8" />
              <rect width="16" height="12" x="4" y="8" rx="2" />
              <path d="M2 14h2" />
              <path d="M20 14h2" />
              <path d="M15 13v2" />
              <path d="M9 13v2" />
            </svg>
          )}
        </button>
        {/* Badge de no leídos */}
        {!open && unreadCount > 0 && (
          <span class="badge" aria-label={`${unreadCount} mensajes no leídos`}>
            {unreadCount > 9 ? "9+" : unreadCount}
          </span>
        )}
      </div>
    </div>
  );
}

class ChatbotWidgetElement extends HTMLElement {
  private _mounted = false;

  connectedCallback() {
    if (this._mounted) return;
    this._mounted = true;
    // Regla cardinal: fallar en silencio, nunca romper la página anfitriona.
    try {
      this._mount();
    } catch (err) {
      try { console.error("[chatbot-widget] mount failed", err); } catch { /* noop */ }
    }
  }

  private _mount() {
    const shadow = this.attachShadow({ mode: "open" });

    const style = document.createElement("style");
    style.textContent = STYLES;
    shadow.appendChild(style);

    const container = document.createElement("div");
    shadow.appendChild(container);

    const apiUrl          = this.getAttribute("api-url") ?? "";
    const apiKey          = this.getAttribute("api-key") ?? "";
    const chatbotName     = this.getAttribute("chatbot-name") ?? "Asistente Virtual";
    const welcomeMessage  =
      this.getAttribute("welcome-message") ??
      this.getAttribute("greeting-message") ??
      "¡Hola! ¿En qué puedo ayudarte?";
    const openOnLoad      = this.getAttribute("open-on-load") === "true";
    const suggestions     = parseSuggestions(this.getAttribute("suggestions"));
    const proactiveMessage = this.getAttribute("proactive-message") ?? "";
    const position        = parsePosition(this.getAttribute("position"));
    const showBotIcon     = this.getAttribute("show-bot-icon") !== "false";
    const launcherLabel   = this.getAttribute("launcher-label") ?? "";

    function applyPrimaryColor(color: string) {
      const host = shadow.host as HTMLElement;
      host.style.setProperty("--color-primary", color);
      host.style.setProperty("--color-primary-hover", color);
      host.style.setProperty("--color-bubble", color);
    }

    render(
      <ChatWidget
        apiUrl={apiUrl}
        apiKey={apiKey}
        chatbotName={chatbotName}
        welcomeMessage={welcomeMessage}
        openOnLoad={openOnLoad}
        suggestions={suggestions}
        proactiveMessage={proactiveMessage}
        position={position}
        showBotIcon={showBotIcon}
        launcherLabel={launcherLabel}
        applyPrimaryColor={applyPrimaryColor}
      />,
      container,
    );
  }
}

function parsePosition(raw: string | null): WidgetPosition {
  const valid: WidgetPosition[] = ["bottom-right", "bottom-left", "top-right", "top-left"];
  if (raw && (valid as string[]).includes(raw)) return raw as WidgetPosition;
  return "bottom-right";
}

function parseSuggestions(raw: string | null): string[] {
  if (!raw) return [];
  const trimmed = raw.trim();
  if (!trimmed) return [];
  if (trimmed.startsWith("[")) {
    try {
      const parsed = JSON.parse(trimmed);
      if (Array.isArray(parsed)) return parsed.filter((s) => typeof s === "string" && s.trim().length > 0);
    } catch { /* fallthrough a CSV */ }
  }
  return trimmed.split(",").map((s) => s.trim()).filter(Boolean);
}

if (!customElements.get("chatbot-widget")) {
  customElements.define("chatbot-widget", ChatbotWidgetElement);
}

function autoInit() {
  if (document.querySelector("chatbot-widget")) return;
  const script =
    document.currentScript ??
    document.querySelector<HTMLScriptElement>("script[data-api-key]");
  if (!script) return;
  const el = document.createElement("chatbot-widget");
  el.setAttribute("api-url", script.getAttribute("data-api-url") ?? "");
  el.setAttribute("api-key", script.getAttribute("data-api-key") ?? "");
  const passthrough = [
    "data-open-on-load",
    "data-greeting-message",
    "data-chatbot-name",
    "data-suggestions",
    "data-proactive-message",
    "data-position",
    "data-show-bot-icon",
    "data-launcher-label",
  ];
  passthrough.forEach((attr) => {
    const v = script.getAttribute(attr);
    if (v !== null) el.setAttribute(attr.replace(/^data-/, ""), v);
  });
  document.body.appendChild(el);
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", autoInit);
} else {
  autoInit();
}
