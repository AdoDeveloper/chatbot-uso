"use client";

import { useEffect, useState, useRef } from "react";
import { createPortal } from "react-dom";
import { Marked } from "marked";
import {
  Loader2, Send, RotateCcw, FileText, Copy, Check, X, Bot,
  ThumbsUp, ThumbsDown, GitBranch, Rocket, Globe, Zap,
  MessageSquare, Monitor, MoreVertical, Volume2, Square, Accessibility, LogOut,
} from "lucide-react";
import api, { tokenStore } from "@/lib/api";
import { getErrorMessage } from "@/hooks/use-api";
import { useAuth } from "@/contexts/auth-context";
import { useToast } from "@/components/ui/toast";
import { SegmentedControl } from "@/components/composed/segmented-control";
import type { ChatbotSettings, WidgetConfig } from "@/types";

import { BASE_URL } from "@/lib/config";
const CHAT_API_URL = `${BASE_URL}/api/v1/chat`;

// marked v10+: instanciar con opciones, usar parseInline sync o lexer+parser
const _marked = new Marked({ breaks: true, gfm: true, async: false });
_marked.use({
  renderer: {
    link({ href, text }: { href: string; text: string }) {
      const isPdf = /\.pdf(\?.*)?$/i.test(href || "");
      const cls = isPdf ? ' class="pdf-link"' : "";
      return `<a href="${href}" target="_blank" rel="noopener noreferrer"${cls}>${text}</a>`;
    },
  },
});

// DOMPurify needs the browser DOM — lazy-load it client-side only.
let _purify: ((html: string) => string) | null = null;
if (typeof window !== "undefined") {
  import("dompurify").then((m) => {
    _purify = (html: string) => m.default.sanitize(html, { ADD_ATTR: ["target"] });
  });
}

function maybePortal(condition: boolean, node: React.ReactElement): React.ReactNode {
  if (!condition) return node;
  if (typeof document === "undefined") return node;
  return createPortal(node, document.body);
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
function renderMarkdown(text: string): string {
  const raw = _marked.parse(text) as string;
  if (!_purify) return escapeHtml(text);
  return _purify(raw);
}

interface Message {
  role: "user" | "assistant";
  content: string;
  id?: string;
  feedback?: "positive" | "negative";
  sources?: { source: string; score: number; text: string }[];
  copied?: boolean;
}

type PlaygroundMode = "draft" | "deployed";

const _PG_STORAGE_KEY = "playground_session";

function SourceCard({
  source, score, text, index,
}: { source: string; score: number; text: string; index: number }) {
  const color =
    score > 0.7 ? "#16a34a" : score > 0.4 ? "#ca8a04" : "#dc2626";
  return (
    <div className="border border-border rounded-lg p-2.5 space-y-1.5 bg-card">
      <div className="flex items-center gap-1.5">
        <span className="text-3xs font-mono text-muted-foreground w-3 shrink-0">
          {index + 1}
        </span>
        <FileText className="w-3 h-3 text-muted-foreground shrink-0" />
        <span className="text-2xs font-medium text-foreground flex-1 min-w-0 truncate">
          {source}
        </span>
        <span
          className="text-3xs font-mono font-bold shrink-0"
          style={{ color }}
        >
          {score.toFixed(2)}
        </span>
      </div>
      <p className="text-2xs text-muted-foreground line-clamp-2 leading-relaxed pl-5">
        {text}
      </p>
      <div className="pl-5">
        <div className="h-1 bg-muted rounded-full overflow-hidden">
          <div
            className="h-full rounded-full transition-all"
            style={{ width: `${score * 100}%`, backgroundColor: color + "55" }}
          />
        </div>
      </div>
    </div>
  );
}

// Tab: Previsualizar
export function PlaygroundTab({
  settings,
  savedSettings,
  widgetConfig,
  deployedWidgetConfig,
}: {
  settings: ChatbotSettings;
  savedSettings: ChatbotSettings | null;
  widgetConfig: WidgetConfig | null;
  deployedWidgetConfig?: WidgetConfig | null;
}) {
  const { toast } = useToast();
  const { logout } = useAuth();

  const sessionIdRef = useRef<string>(
    (() => {
      try {
        return (
          sessionStorage.getItem("playground_session_id") ??
          crypto.randomUUID()
        );
      } catch {
        return crypto.randomUUID();
      }
    })(),
  );

  const [messages, setMessages] = useState<Message[]>(() => {
    try {
      const stored = sessionStorage.getItem(_PG_STORAGE_KEY);
      return stored ? JSON.parse(stored) : [];
    } catch {
      return [];
    }
  });
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [lastSources, setLastSources] = useState<
    { source: string; score: number; text: string }[]
  >([]);
  const [meta, setMeta] = useState<{
    provider?: string;
    model?: string;
    latency?: number;
  } | null>(null);
  const [mode, setMode] = useState<PlaygroundMode>("draft");
  const [widgetOpen, setWidgetOpen] = useState(true);
  // CSAT — mismos 4 estados que el widget real para paridad estricta.
  const [csatState, setCsatState] = useState<"hidden" | "pending" | "comment" | "submitted">(
    "hidden",
  );
  const [csatScore, setCsatScore] = useState(0);
  const [csatComment, setCsatComment] = useState("");
  // Escalamiento simulado — replica el flujo del widget real. En el preview
  // no se despacha nada al backend; es solo visual para que el admin vea
  // exactamente cómo se comporta con su configuración.
  const [escalState, setEscalState] = useState<"hidden" | "prompt" | "form" | "submitted" | "continue">("hidden");
  const [escalType, setEscalType] = useState<"email" | "whatsapp">("email");
  const [escalValue, setEscalValue] = useState("");
  const [escalError, setEscalError] = useState("");
  // Header kebab + accesibilidad (paridad con el widget real).
  const [kebabOpen, setKebabOpen] = useState(false);
  const [a11yOpen, setA11yOpen] = useState(false);
  const [textScale, setTextScale] = useState<"sm" | "md" | "lg">("md");
  const [highContrast, setHighContrast] = useState(false);
  const [speakingId, setSpeakingId] = useState<string | null>(null);
  const chatScrollRef = useRef<HTMLDivElement>(null);

  // Mismo breakpoint que las clases `md:` de este componente (768px) — el
  // chat abierto se porta a un overlay `fixed inset-0` de pantalla completa
  // en vez de quedar contenido dentro de la card acotada a 82dvh, que en
  // mobile perdía el input cuando la conversación crecía.
  const [isMobilePreview, setIsMobilePreview] = useState(false);
  useEffect(() => {
    const mql = window.matchMedia("(max-width: 767px)");
    const onChange = () => setIsMobilePreview(mql.matches);
    onChange();
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  }, []);

  const ttsBrowserSupported = typeof window !== "undefined" && !!window.speechSynthesis;
  function speakMessage(id: string, text: string) {
    try {
      const synth = window.speechSynthesis;
      if (!synth) return;
      if (speakingId === id) { synth.cancel(); setSpeakingId(null); return; }
      synth.cancel();
      const clean = text.replace(/[*_`#>]/g, "").replace(/\[(.*?)\]\(.*?\)/g, "$1");
      const utter = new SpeechSynthesisUtterance(clean);
      utter.lang = "es-ES";
      utter.onend = () => setSpeakingId(null);
      utter.onerror = () => setSpeakingId(null);
      setSpeakingId(id);
      synth.speak(utter);
    } catch { setSpeakingId(null); }
  }
  const msgScaleClass = textScale === "sm" ? "text-2xs" : textScale === "lg" ? "text-sm leading-relaxed" : "text-xs";

  // Misma validación que el widget real (paridad estricta).
  function validateContact(type: "email" | "whatsapp", value: string): string {
    const v = value.trim();
    if (!v) return type === "email" ? "Ingrese su correo electrónico." : "Ingrese su número de WhatsApp.";
    if (type === "email") {
      if (!/^[^\s@]+@[^\s@]+\.[^\s@]{2,}$/.test(v)) return "Ingrese un correo electrónico válido.";
    } else {
      const digits = v.replace(/[\s\-()]/g, "");
      if (!/^\+?\d{8,15}$/.test(digits)) return "Ingrese un número de WhatsApp válido (8 a 15 dígitos).";
    }
    return "";
  }

  function submitEscalationPreview() {
    const err = validateContact(escalType, escalValue);
    if (err) { setEscalError(err); return; }
    setEscalError("");
    setEscalState("submitted");
    // Paridad con el widget real: la confirmación "✓ Listo" es transitoria.
    // Tras un momento para leerla, se oculta el escalamiento y se pasa a CSAT
    // (o el chat vuelve a su estado normal si CSAT está deshabilitado). No se
    // deja como burbuja permanente en el historial.
    setTimeout(() => {
      setEscalState("hidden");
      if (enableCsat) setCsatState("pending");
    }, 2200);
  }

  // Active settings according to mode
  const activeSettings =
    mode === "deployed" && savedSettings ? savedSettings : settings;
  const activeWidgetConfig =
    mode === "deployed" && deployedWidgetConfig
      ? deployedWidgetConfig
      : widgetConfig;

  const primaryColor = activeWidgetConfig?.primary_color ?? "#1C386D";
  const chatbotName =
    activeWidgetConfig?.chatbot_name ??
    activeSettings.chatbot_name ??
    "Asistente";
  const welcomeMessage =
    activeWidgetConfig?.welcome_message ??
    activeSettings.welcome_message ??
    "¡Hola! ¿En qué puedo ayudarte?";
  const showBotIcon = activeWidgetConfig?.show_bot_icon ?? true;
  const suggestions: string[] = activeWidgetConfig?.suggestions ?? [];
  const logoUrl = activeWidgetConfig?.logo_url ?? null;
  const showSources = activeWidgetConfig?.show_sources ?? true;
  const enableCopyAction = activeWidgetConfig?.enable_copy_action ?? true;
  const enableFeedbackIcons = activeWidgetConfig?.enable_feedback_icons ?? true;
  const enableAccessibility = activeWidgetConfig?.enable_accessibility ?? true;
  // Esquina donde se ancla el widget flotante (paridad con data-position del
  // widget real: bottom-right, bottom-left, top-right, top-left).
  const widgetPosition = activeWidgetConfig?.position ?? "bottom-right";
  const isTopPosition = widgetPosition.startsWith("top-");
  const isLeftPosition = widgetPosition.endsWith("-left");
  const widgetCornerClass = `${isTopPosition ? "md:top-4" : "md:bottom-4"} ${isLeftPosition ? "md:left-4 md:items-start" : "md:right-4 md:items-end"}`;
  // TTS efectivo = el navegador lo soporta Y el admin lo habilitó Y el menú
  // de accesibilidad no está desactivado (paridad con el widget).
  const ttsSupported = ttsBrowserSupported && (activeWidgetConfig?.enable_tts ?? true) && enableAccessibility;
  const showEndChatButton = activeWidgetConfig?.show_end_chat_button ?? true;
  const showNewChatButton = activeWidgetConfig?.show_new_chat_button ?? true;
  const enableCsat = activeWidgetConfig?.enable_csat ?? false;
  const csatQuestion =
    activeWidgetConfig?.csat_question ??
    "¿Cómo calificarías esta conversación?";
  const enableEscalation = activeWidgetConfig?.enable_escalation ?? true;
  const launcherLabel = activeWidgetConfig?.launcher_label ?? "";
  const proactiveMessage = activeWidgetConfig?.proactive_message ?? "";

  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => { abortRef.current?.abort(); }, []);

  const prevLoadingRef = useRef(false);
  useEffect(() => {
    const justFinished = prevLoadingRef.current && !loading;
    prevLoadingRef.current = loading;
    const el = chatScrollRef.current;
    if (el && (!loading || justFinished)) {
      el.scrollTo({ top: el.scrollHeight, behavior: "smooth" });
    }
  }, [messages, loading]);

  useEffect(() => {
    try {
      sessionStorage.setItem(_PG_STORAGE_KEY, JSON.stringify(messages));
      sessionStorage.setItem("playground_session_id", sessionIdRef.current);
    } catch {
      /* storage full */
    }
  }, [messages]);

  const skipModeReset = useRef(true);
  useEffect(() => {
    if (skipModeReset.current) {
      skipModeReset.current = false;
      return;
    }
    setMessages([]);
    setLastSources([]);
    setMeta(null);
    setCsatState("hidden");
    setCsatScore(0);
    sessionIdRef.current = crypto.randomUUID();
    try {
      sessionStorage.removeItem(_PG_STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, [mode]);

  function resetConversation() {
    setMessages([]);
    setLastSources([]);
    setMeta(null);
    setCsatState("hidden");
    setCsatScore(0);
    setCsatComment("");
    setEscalState("hidden");
    setEscalValue("");
    setEscalError("");
    sessionIdRef.current = crypto.randomUUID();
    try {
      sessionStorage.removeItem(_PG_STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }

  function endChat() {
    if (enableCsat && messages.some((m) => m.role === "assistant" && m.id)) {
      setCsatState("pending");
    } else {
      resetConversation();
    }
  }

  async function copyMessage(msgId: string, content: string) {
    try {
      await navigator.clipboard.writeText(content);
      setMessages((prev) =>
        prev.map((m) => (m.id === msgId ? { ...m, copied: true } : m)),
      );
      setTimeout(() => {
        setMessages((prev) =>
          prev.map((m) => (m.id === msgId ? { ...m, copied: false } : m)),
        );
      }, 1500);
    } catch {
      /* clipboard blocked */
    }
  }

  async function handleFeedback(msgId: string, value: "positive" | "negative") {
    try {
      await api.patch(`/conversations/messages/${msgId}/feedback`, {
        feedback: value,
      });
      setMessages((prev) =>
        prev.map((m) => (m.id === msgId ? { ...m, feedback: value } : m)),
      );
    } catch (err) {
      toast({ type: "error", message: getErrorMessage(err, "No se pudo guardar la valoración.") });
    }
  }

  async function handleSend(question?: string) {
    const q = (question ?? input).trim();
    if (!q || loading) return;

    // Simulación de escalamiento en el preview: si está habilitado y el
    // usuario pide un humano, se muestra el prompt Sí/No igual que lo haría
    // el widget real cuando una regla de escalamiento dispara. En el preview
    // no se despacha nada al backend (is_playground no evalúa reglas).
    if (enableEscalation && escalState === "hidden" && /humano|persona|agente|asesor|alguien real/i.test(q)) {
      setMessages((prev) => [...prev, { role: "user", content: q }]);
      setInput("");
      setEscalState("prompt");
      return;
    }

    const history = messages
      .slice(-10)
      .map((m) => ({ role: m.role, content: m.content }));

    setMessages((prev) => [...prev, { role: "user", content: q }]);
    setInput("");
    setLoading(true);
    setLastSources([]);
    setMeta(null);
    setMessages((prev) => [...prev, { role: "assistant", content: "" }]);

    try {
      const accessToken = tokenStore.getAccess();
      abortRef.current?.abort();
      abortRef.current = new AbortController();

      const response = await fetch(CHAT_API_URL, {
        method: "POST",
        signal: abortRef.current.signal,
        headers: {
          "Content-Type": "application/json",
          ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
        },
        body: JSON.stringify({
          question: q,
          session_id: sessionIdRef.current,
          messages: history.length > 0 ? history : undefined,
          browser: "playground",
          ...(mode === "deployed" ? { source_scope: "production" } : {}),
        }),
      });

      if (response.status === 401) {
        setMessages((prev) => prev.filter((m) => !(m.role === "assistant" && m.content === "")));
        setLoading(false);
        await logout();
        return;
      }
      if (!response.ok)
        throw new Error(`HTTP ${response.status}`);

      // Respuesta completa (sin streaming): mientras se espera, la burbuja
      // del asistente queda con content: "" mostrando el indicador de
      // "escribiendo..."; al llegar la respuesta se rellena de una vez.
      const event = await response.json();

      if (event.type === "error") {
        const msg = event.message ?? "Error desconocido";
        setMessages((prev) => {
          const u = [...prev];
          u[u.length - 1] = { role: "assistant", content: msg };
          return u;
        });
      } else {
        const mapped = (event.sources ?? []).map(
          (s: { source_name: string; score: number; text: string }) => ({
            source: s.source_name,
            score: s.score,
            text: s.text,
          }),
        );
        setLastSources(mapped);
        setMessages((prev) => {
          const u = [...prev];
          u[u.length - 1] = {
            role: "assistant",
            content: event.content ?? "",
            sources: mapped,
            id: event.message_id,
          };
          return u;
        });
        setMeta({
          provider: event.provider_name,
          model: event.model_name,
          latency: event.latency_ms,
        });
      }
    } catch {
      setMessages((prev) => {
        const u = [...prev];
        if (
          u[u.length - 1]?.role === "assistant" &&
          u[u.length - 1].content === ""
        )
          u[u.length - 1] = {
            role: "assistant",
            content: "⚠️ No se pudo conectar con el backend.",
          };
        return u;
      });
    } finally {
      setLoading(false);
    }
  }

  const showSuggestions = messages.length === 0 && suggestions.length > 0;

  return (
    <div className="flex flex-col gap-4">
      {/* ── Top mode bar ── */}
      <div className="flex items-center gap-3 pb-4 border-b border-border">
        <Monitor className="w-4 h-4 text-muted-foreground shrink-0" />
        <span className="text-13 font-medium text-foreground">Vista previa</span>
        <div className="ml-auto flex items-center gap-2.5">
          <SegmentedControl
            ariaLabel="Entorno de vista previa"
            value={mode}
            onChange={setMode}
            options={[
              { value: "draft", label: "Pruebas", icon: GitBranch },
              { value: "deployed", label: "Producción", icon: Rocket },
            ]}
          />
          <span
            className={`hidden sm:inline-flex text-2xs px-2.5 py-0.5 rounded-full font-medium ${
              mode === "draft"
                ? "text-warning"
                : "bg-success/10 text-success"
            }`}
          >
            {mode === "draft"
              ? "Entorno de pruebas"
              : "Entorno de producción"}
          </span>
        </div>
      </div>

      {/* ── Main two-column layout ──
          Altura acotada también en mobile (no solo md:) para que el chat
          tenga scroll interno en vez de crecer y empujar el resto de la
          página. En mobile usa una fracción del viewport; desde md: la
          ventana flotante de tamaño fijo.
          dvh en vez de vh: vh mide el viewport de layout completo (fijo),
          dvh se ajusta al viewport visual real — con vh, al abrir el
          teclado el chat quedaba parcialmente tapado (el input inaccesible)
          porque 82vh seguía calculando sobre la altura sin teclado. */}
      <div
        className="flex flex-col md:flex-row rounded-xl border border-border overflow-hidden h-[82vh] h-[82dvh] md:h-[580px]"
      >
        {/* ── Left: page simulation ── */}
        {/* En mobile no hay espacio real para simular una página de fondo:
            el chat ocuparía casi todo el ancho igual, dejando el "browser
            chrome" y el skeleton fantasma como una tira inútil detrás. Se
            oculta bajo md: y el chat pasa a ocupar el panel completo. */}
        <div className="flex-1 relative overflow-hidden bg-slate-100 dark:bg-slate-800/60 flex flex-col min-h-0">
          {/* Browser chrome */}
          <div className="hidden md:flex bg-white dark:bg-slate-900 border-b border-border/50 px-3 py-2 items-center gap-2 shrink-0">
            <div className="flex gap-1">
              <div className="w-2.5 h-2.5 rounded-full bg-red-400/60" />
              <div className="w-2.5 h-2.5 rounded-full bg-yellow-400/60" />
              <div className="w-2.5 h-2.5 rounded-full bg-green-400/60" />
            </div>
            <div className="flex-1 mx-2 bg-muted/70 rounded px-2.5 py-0.5 flex items-center gap-1.5 max-w-xs">
              <Globe className="w-2.5 h-2.5 text-muted-foreground shrink-0" />
              <span className="text-3xs text-muted-foreground truncate">
                https://www.universidad.edu.sv
              </span>
            </div>
          </div>

          {/* Fake webpage skeleton */}
          <div className="hidden md:block flex-1 overflow-hidden p-6 pointer-events-none select-none">
            <div className="max-w-lg">
              <div className="h-6 bg-white/70 dark:bg-white/10 rounded-md w-48 mb-4" />
              <div className="space-y-2 mb-6">
                {[95, 88, 92, 76, 83].map((w, i) => (
                  <div
                    key={i}
                    className="h-2.5 bg-white/60 dark:bg-white/10 rounded"
                    style={{ width: `${w}%` }}
                  />
                ))}
              </div>
              <div className="grid grid-cols-2 gap-2.5 mb-6">
                {[1, 2, 3, 4].map((i) => (
                  <div
                    key={i}
                    className="h-14 bg-white/50 dark:bg-white/10 rounded-lg"
                  />
                ))}
              </div>
              <div className="h-4 bg-white/60 dark:bg-white/10 rounded w-32 mb-3" />
              <div className="space-y-2">
                {[72, 86, 68].map((w, i) => (
                  <div
                    key={i}
                    className="h-2.5 bg-white/50 dark:bg-white/10 rounded"
                    style={{ width: `${w}%` }}
                  />
                ))}
              </div>
            </div>
          </div>

          {/* ── Widget: pantalla completa en mobile, flotante en la esquina
              configurada desde md: (paridad con data-position del widget real). ── */}
          <div className={`flex-1 min-h-0 flex flex-col items-center justify-center md:justify-start md:absolute md:inset-auto md:flex-none gap-2.5 ${widgetCornerClass}`}>
            {/* En mobile, con el chat cerrado, se muestra un estado vacío
                claro en vez de dejar solo el fondo gris con un botón
                flotando sin contexto. */}
            {!widgetOpen && (
              <div className="md:hidden flex flex-col items-center gap-2.5 px-6 text-center">
                <MessageSquare className="w-9 h-9 text-muted-foreground/30" />
                <p className="text-13 text-muted-foreground">
                  Toque el botón para abrir el chat de prueba.
                </p>
              </div>
            )}
            {/* Proactive message (only when widget is closed). El simulador
                emula un sitio web real (siempre claro), por eso se fijan
                colores explícitos en vez de usar variantes dark: del panel. */}
            {!widgetOpen && proactiveMessage && (
              <div className="bg-white text-slate-800 border border-slate-200 rounded-2xl shadow-lg px-3 py-2 text-xs max-w-[70vw] md:max-w-[200px] text-center md:text-left">
                {proactiveMessage}
              </div>
            )}

            {/* Chat panel — overlay fijo de pantalla completa real en
                mobile (portal a document.body, fuera de la card acotada a
                82dvh: si quedaba dentro del flujo normal, el input se
                perdía al crecer la conversación), ventana flotante de
                tamaño fijo desde md: (simula el widget embebido). */}
            {widgetOpen && maybePortal(
              isMobilePreview,
              <div
                className={
                  isMobilePreview
                    ? "fixed inset-0 z-100 overflow-hidden flex flex-col bg-background"
                    : "rounded-none md:rounded-2xl overflow-hidden flex flex-col shadow-2xl border-0 md:border border-border bg-background flex-1 w-full md:w-[340px] md:flex-none md:max-w-[calc(100vw-3rem)] md:h-[440px] md:max-h-[calc(100%-1rem)]"
                }
              >
                {/* Widget header */}
                <div
                  className="flex items-center gap-2.5 px-3.5 py-2.5 shrink-0"
                  style={{ backgroundColor: primaryColor }}
                >
                  {showBotIcon && (
                    <div className="w-7 h-7 rounded-full bg-white/20 flex items-center justify-center shrink-0 overflow-hidden">
                      {logoUrl ? (
                        <img
                          src={logoUrl}
                          alt={chatbotName}
                          className="w-full h-full object-cover"
                        />
                      ) : (
                        <Bot className="w-3.5 h-3.5 text-white" />
                      )}
                    </div>
                  )}
                  <div className="flex-1 min-w-0">
                    <p className="text-xs font-semibold text-white truncate">
                      {chatbotName}
                    </p>
                    <p className="text-3xs text-white/70">En línea</p>
                  </div>
                  {/* Kebab (⋮) — paridad con el widget real: agrupa Nueva
                      conversación, Accesibilidad y Finalizar chat. Se oculta
                      si no hay ningún ítem que mostrar. */}
                  {(showNewChatButton || enableAccessibility || showEndChatButton) && (
                  <div className="relative">
                    <button
                      type="button"
                      onClick={() => setKebabOpen((v) => !v)}
                      className="w-7 h-7 flex items-center justify-center rounded text-white/70 hover:text-white hover:bg-white/10 transition-colors"
                      aria-label="Más opciones"
                      aria-expanded={kebabOpen}
                      aria-haspopup="menu"
                    >
                      <MoreVertical className="w-5 h-5" />
                    </button>
                    {kebabOpen && (
                      <div role="menu" className="absolute right-0 top-7 z-10 min-w-[170px] bg-popover border border-border rounded-lg shadow-lg py-1 text-foreground">
                        {showNewChatButton && messages.length > 0 && (
                          <button type="button" role="menuitem" onClick={() => { resetConversation(); setKebabOpen(false); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] hover:bg-muted-foreground/10 text-left">
                            <RotateCcw className="w-3.5 h-3.5" /> Nueva conversación
                          </button>
                        )}
                        {enableAccessibility && (
                          <button type="button" role="menuitem" onClick={() => { setA11yOpen(true); setKebabOpen(false); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] hover:bg-muted-foreground/10 text-left">
                            <Accessibility className="w-3.5 h-3.5" /> Accesibilidad
                          </button>
                        )}
                        {showEndChatButton && (
                          <button type="button" role="menuitem" onClick={() => { endChat(); setKebabOpen(false); }} className="w-full flex items-center gap-2 px-3 py-1.5 text-[12px] hover:bg-muted-foreground/10 text-left text-destructive">
                            <LogOut className="w-3.5 h-3.5" /> Finalizar chat
                          </button>
                        )}
                      </div>
                    )}
                  </div>
                  )}
                  {/* Cerrar el simulador (paridad con el botón ✕ del widget real). */}
                  <button
                    type="button"
                    onClick={() => setWidgetOpen(false)}
                    className="w-7 h-7 flex items-center justify-center rounded text-white/70 hover:text-white hover:bg-white/10 transition-colors"
                    title="Cerrar"
                    aria-label="Cerrar"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>

                {/* Panel de accesibilidad (paridad con el widget real) */}
                {a11yOpen && (
                  <div className="border-b border-border bg-muted/40 px-3 py-2.5 space-y-2.5">
                    <div className="flex items-center justify-between">
                      <span className="text-2xs font-semibold text-foreground flex items-center gap-1.5">
                        <Accessibility className="w-3.5 h-3.5" /> Accesibilidad
                      </span>
                      <button
                        type="button"
                        onClick={() => setA11yOpen(false)}
                        className="p-1 -m-1 rounded text-muted-foreground/70 hover:text-foreground hover:bg-muted-foreground/10"
                        aria-label="Cerrar accesibilidad"
                      >
                        <X className="w-3.5 h-3.5" />
                      </button>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-2xs text-muted-foreground">Tamaño de texto</span>
                      <div role="radiogroup" aria-label="Tamaño de texto" className="flex items-center gap-1">
                        {([["sm", "A", "text-2xs"], ["md", "A", "text-xs"], ["lg", "A", "text-sm"]] as const).map(([val, label, cls]) => (
                          <button
                            key={val}
                            type="button"
                            role="radio"
                            aria-checked={textScale === val}
                            onClick={() => setTextScale(val)}
                            className={`w-7 h-7 flex items-center justify-center rounded-md border font-semibold ${cls} ${
                              textScale === val
                                ? "border-transparent text-white"
                                : "border-border text-muted-foreground hover:bg-muted-foreground/10"
                            }`}
                            style={textScale === val ? { backgroundColor: primaryColor } : {}}
                          >
                            {label}
                          </button>
                        ))}
                      </div>
                    </div>
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-2xs text-muted-foreground">Alto contraste</span>
                      <button
                        type="button"
                        role="switch"
                        aria-checked={highContrast}
                        onClick={() => setHighContrast((v) => !v)}
                        className={`relative w-9 h-5 rounded-full transition-colors ${highContrast ? "" : "bg-muted-foreground/30"}`}
                        style={highContrast ? { backgroundColor: primaryColor } : {}}
                      >
                        <span className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white transition-transform ${highContrast ? "translate-x-4" : ""}`} />
                      </button>
                    </div>
                    {ttsSupported && (
                      <p className="text-3xs text-muted-foreground/80 leading-snug">
                        Use el botón <Volume2 className="inline w-3 h-3 align-text-bottom" /> en cada respuesta para escucharla en voz alta.
                      </p>
                    )}
                  </div>
                )}

                {/* Messages */}
                <div ref={chatScrollRef} className="flex-1 overflow-y-auto bg-background p-3 space-y-2.5">
                  {/* Welcome bubble */}
                  <div className="flex items-end gap-1.5">
                    {showBotIcon && (
                      <div
                        className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 mb-0.5 overflow-hidden"
                        style={{ backgroundColor: primaryColor }}
                      >
                        {logoUrl ? (
                          <img
                            src={logoUrl}
                            alt=""
                            className="w-full h-full object-cover"
                          />
                        ) : (
                          <Bot className="w-2.5 h-2.5 text-white" />
                        )}
                      </div>
                    )}
                    <div
                      className={`max-w-[82%] px-3 py-2 rounded-2xl rounded-bl-sm leading-relaxed ${msgScaleClass} ${
                        highContrast
                          ? "bg-black text-white border border-white/40"
                          : "bg-muted text-foreground"
                      }`}
                    >
                      {welcomeMessage}
                    </div>
                  </div>

                  {/* Conversation */}
                  {messages.map((msg, i) => (
                    <div
                      key={i}
                      className={`flex flex-col gap-1 ${msg.role === "user" ? "items-end" : "items-start"}`}
                    >
                      <div
                        className={`flex items-end gap-1.5 w-full ${msg.role === "user" ? "justify-end" : "justify-start"}`}
                      >
                        {msg.role === "assistant" && showBotIcon && (
                          <div
                            className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 mb-0.5 overflow-hidden"
                            style={{ backgroundColor: primaryColor }}
                          >
                            {logoUrl ? (
                              <img
                                src={logoUrl}
                                alt=""
                                className="w-full h-full object-cover"
                              />
                            ) : (
                              <Bot className="w-2.5 h-2.5 text-white" />
                            )}
                          </div>
                        )}
                        <div
                          className={`max-w-[82%] px-3 py-2 leading-relaxed ${msgScaleClass} ${
                            msg.role === "user"
                              ? "text-white rounded-2xl rounded-br-sm whitespace-pre-wrap"
                              : highContrast
                                ? "bg-black text-white border border-white/40 rounded-2xl rounded-bl-sm"
                                : "bg-muted text-foreground rounded-2xl rounded-bl-sm"
                          }`}
                          style={
                            msg.role === "user"
                              ? { backgroundColor: primaryColor }
                              : {}
                          }
                        >
                          {msg.role === "assistant" ? (
                            msg.content ? (
                              <div
                                className="md-content"
                                style={{ "--pdf-link-color": primaryColor } as React.CSSProperties}
                                dangerouslySetInnerHTML={{ __html: renderMarkdown(msg.content) }}
                              />
                            ) : loading && i === messages.length - 1 ? (
                              <span className="flex items-center gap-0.5 h-3">
                                <span className="w-1 h-1 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:-0.3s]" />
                                <span className="w-1 h-1 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:-0.15s]" />
                                <span className="w-1 h-1 rounded-full bg-muted-foreground/50 animate-bounce" />
                              </span>
                            ) : null
                          ) : (
                            msg.content ||
                            (loading && i === messages.length - 1 ? (
                              <span className="flex items-center gap-0.5 h-3">
                                <span className="w-1 h-1 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:-0.3s]" />
                                <span className="w-1 h-1 rounded-full bg-muted-foreground/50 animate-bounce [animation-delay:-0.15s]" />
                                <span className="w-1 h-1 rounded-full bg-muted-foreground/50 animate-bounce" />
                              </span>
                            ) : (
                              ""
                            ))
                          )}
                        </div>
                      </div>

                      {/* Source pills below assistant message */}
                      {msg.role === "assistant" &&
                        showSources &&
                        msg.sources &&
                        msg.sources.length > 0 && (
                          <div
                            className={`flex flex-wrap gap-1 ${showBotIcon ? "pl-7" : "pl-1"}`}
                          >
                            {msg.sources.slice(0, 3).map((s, si) => (
                              <span
                                key={si}
                                className="inline-flex items-center gap-1 px-1.5 py-0.5 text-3xs font-medium rounded-full bg-muted/80 border border-border text-muted-foreground"
                                title={s.text}
                              >
                                <FileText className="w-3 h-3" />
                                {s.source}
                              </span>
                            ))}
                          </div>
                        )}

                      {/* Copy + feedback */}
                      {msg.role === "assistant" &&
                        msg.id &&
                        msg.content &&
                        (ttsSupported || enableCopyAction || enableFeedbackIcons) && (
                          <div
                            className={`flex items-center gap-0.5 ${showBotIcon ? "pl-7" : "pl-1"}`}
                          >
                            {ttsSupported && (
                              <button
                                type="button"
                                onClick={() => speakMessage(msg.id!, msg.content)}
                                className={`p-1.5 -m-1 rounded transition-colors ${
                                  speakingId === msg.id
                                    ? "text-brand-green"
                                    : "text-muted-foreground/60 hover:text-foreground hover:bg-muted-foreground/10"
                                }`}
                                title={speakingId === msg.id ? "Detener lectura" : "Leer en voz alta"}
                              >
                                {speakingId === msg.id ? (
                                  <Square className="w-3.5 h-3.5" />
                                ) : (
                                  <Volume2 className="w-3.5 h-3.5" />
                                )}
                              </button>
                            )}
                            {enableCopyAction && (
                              <button
                                type="button"
                                onClick={() =>
                                  copyMessage(msg.id!, msg.content)
                                }
                                className="p-1.5 -m-1 rounded text-muted-foreground/60 hover:text-foreground hover:bg-muted-foreground/10 transition-colors"
                                title={msg.copied ? "Copiado" : "Copiar"}
                              >
                                {msg.copied ? (
                                  <Check className="w-3.5 h-3.5 text-brand-green" />
                                ) : (
                                  <Copy className="w-3.5 h-3.5" />
                                )}
                              </button>
                            )}
                            {enableFeedbackIcons && (
                              <>
                                <button
                                  type="button"
                                  onClick={() =>
                                    handleFeedback(msg.id!, "positive")
                                  }
                                  className={`p-1.5 -m-1 rounded transition-colors ${
                                    msg.feedback === "positive"
                                      ? "text-brand-green"
                                      : "text-muted-foreground/60 hover:text-foreground hover:bg-muted-foreground/10"
                                  }`}
                                >
                                  <ThumbsUp className="w-3.5 h-3.5" />
                                </button>
                                <button
                                  type="button"
                                  onClick={() =>
                                    handleFeedback(msg.id!, "negative")
                                  }
                                  className={`p-1.5 -m-1 rounded transition-colors ${
                                    msg.feedback === "negative"
                                      ? "text-destructive"
                                      : "text-muted-foreground/60 hover:text-foreground hover:bg-muted-foreground/10"
                                  }`}
                                >
                                  <ThumbsDown className="w-3.5 h-3.5" />
                                </button>
                              </>
                            )}
                          </div>
                        )}
                    </div>
                  ))}

                  {/* Escalamiento simulado — burbuja del bot (paridad con widget real) */}
                  {escalState !== "hidden" && (
                    <div className="flex items-end gap-1.5">
                      {showBotIcon && (
                        <div className="w-5 h-5 rounded-full flex items-center justify-center shrink-0 mb-0.5 overflow-hidden" style={{ backgroundColor: primaryColor }}>
                          {logoUrl ? <img src={logoUrl} alt="" className="w-full h-full object-cover" /> : <Bot className="w-2.5 h-2.5 text-white" />}
                        </div>
                      )}
                      <div className={`max-w-[90%] border px-3 py-2.5 rounded-xl text-xs leading-relaxed space-y-2 shadow-sm ${escalState === "submitted" ? "bg-brand-green/10 border-brand-green/30 text-foreground" : "bg-background border-border text-foreground"}`}>
                        {escalState === "prompt" && (
                          <>
                            <p className="font-medium">¿Desea que la universidad se ponga en contacto con usted?</p>
                            <div className="flex gap-1.5">
                              <button type="button" onClick={() => setEscalState("form")} className="flex-1 py-1.5 rounded-lg text-white text-2xs font-medium" style={{ backgroundColor: primaryColor }}>Sí</button>
                              <button type="button" onClick={() => setEscalState("continue")} className="flex-1 py-1.5 rounded-lg border border-border bg-background text-2xs font-medium hover:bg-muted-foreground/10">No</button>
                            </div>
                          </>
                        )}
                        {escalState === "continue" && (
                          <>
                            <p className="font-medium">¿Desea continuar con el asistente virtual?</p>
                            <div className="flex gap-1.5">
                              <button type="button" onClick={() => setEscalState("hidden")} className="flex-1 py-1.5 rounded-lg text-white text-2xs font-medium" style={{ backgroundColor: primaryColor }}>Sí, continuar</button>
                              <button type="button" onClick={() => { setEscalState("hidden"); if (enableCsat) setCsatState("pending"); }} className="flex-1 py-1.5 rounded-lg border border-border bg-background text-2xs font-medium hover:bg-muted-foreground/10">No, finalizar</button>
                            </div>
                          </>
                        )}
                        {escalState === "form" && (
                          <form onSubmit={(e) => { e.preventDefault(); submitEscalationPreview(); }} noValidate>
                            <p className="font-medium" id="pg-escal-title">¿Cómo prefiere que lo contactemos?</p>
                            <div className="flex flex-col gap-1 mt-1.5" role="radiogroup" aria-labelledby="pg-escal-title">
                              <label className="flex items-center gap-1.5 text-2xs cursor-pointer">
                                <input type="radio" name="pg-escal-type" checked={escalType === "email"} onChange={() => { setEscalType("email"); setEscalValue(""); setEscalError(""); }} />
                                Correo electrónico
                              </label>
                              <label className="flex items-center gap-1.5 text-2xs cursor-pointer">
                                <input type="radio" name="pg-escal-type" checked={escalType === "whatsapp"} onChange={() => { setEscalType("whatsapp"); setEscalValue(""); setEscalError(""); }} />
                                WhatsApp
                              </label>
                            </div>
                            <label htmlFor="pg-escal-input" className="block text-3xs font-semibold text-muted-foreground mt-2 mb-0.5">
                              {escalType === "email" ? "Su correo electrónico" : "Su número de WhatsApp"}
                            </label>
                            <input
                              id="pg-escal-input"
                              type={escalType === "email" ? "email" : "tel"}
                              inputMode={escalType === "email" ? "email" : "tel"}
                              className={`w-full h-8 bg-background rounded-lg px-2.5 text-xs outline-none border placeholder:text-muted-foreground/70 ${escalError ? "border-destructive" : "border-border"}`}
                              placeholder={escalType === "email" ? "tucorreo@ejemplo.com" : "+503 7777 7777"}
                              value={escalValue}
                              onChange={(e) => { setEscalValue(e.target.value); if (escalError) setEscalError(""); }}
                              maxLength={200}
                              aria-invalid={escalError ? "true" : "false"}
                              aria-describedby={escalError ? "pg-escal-error" : undefined}
                            />
                            {escalError && (
                              <p id="pg-escal-error" role="alert" className="text-3xs text-destructive font-medium mt-1">{escalError}</p>
                            )}
                            <div className="flex gap-1.5 justify-end mt-2">
                              <button type="button" onClick={() => { setEscalState("hidden"); setEscalError(""); }} className="text-2xs px-2 py-1 text-muted-foreground hover:text-foreground">Cancelar</button>
                              <button
                                type="submit"
                                className="text-2xs px-2.5 py-1 rounded text-white"
                                style={{ backgroundColor: primaryColor }}
                              >Enviar</button>
                            </div>
                          </form>
                        )}
                        {escalState === "submitted" && (
                          <p className="text-success font-medium">✓ Listo. La universidad se pondrá en contacto con usted pronto.</p>
                        )}
                      </div>
                    </div>
                  )}
                </div>

                {/* CSAT — paso 1: estrellas (paridad con widget real) */}
                {enableCsat && csatState === "pending" && (
                  <div className="border-t border-border bg-muted/40 px-3 py-3 shrink-0 flex flex-col items-center gap-2">
                    <p className="text-xs font-medium text-foreground text-center">
                      {csatQuestion}
                    </p>
                    <div className="flex items-center gap-1">
                      {[1, 2, 3, 4, 5].map((n) => (
                        <button
                          key={n}
                          type="button"
                          onClick={() => { setCsatScore(n); setCsatState("comment"); }}
                          onMouseEnter={() => setCsatScore(n)}
                          className="text-2xl leading-none transition-transform hover:scale-110 text-amber-400"
                          aria-label={`${n} estrella${n !== 1 ? "s" : ""}`}
                        >
                          {n <= csatScore ? "★" : "☆"}
                        </button>
                      ))}
                    </div>
                    <button
                      type="button"
                      onClick={() => setCsatState("submitted")}
                      className="text-2xs text-muted-foreground hover:text-foreground"
                    >
                      Omitir valoración
                    </button>
                  </div>
                )}
                {/* CSAT — paso 2: comentario opcional */}
                {enableCsat && csatState === "comment" && (
                  <div className="border-t border-border bg-muted/40 px-3 py-3 shrink-0 flex flex-col items-center gap-2">
                    <p className="text-xs font-medium text-foreground text-center">
                      ¿Quieres agregar un comentario? <span className="font-normal text-muted-foreground">(opcional)</span>
                    </p>
                    <div className="flex items-center gap-0.5">
                      {[1, 2, 3, 4, 5].map((n) => (
                        <span key={n} className={`text-lg leading-none ${n <= csatScore ? "text-amber-400" : "text-muted-foreground/30"}`} aria-hidden="true">★</span>
                      ))}
                    </div>
                    <textarea
                      className="w-full bg-background rounded-lg px-2.5 py-2 text-xs outline-none border border-border resize-none placeholder:text-muted-foreground"
                      placeholder="Cuéntenos su experiencia…"
                      maxLength={300}
                      rows={2}
                      value={csatComment}
                      onChange={(e) => setCsatComment(e.target.value)}
                    />
                    <div className="flex items-center gap-2 self-stretch justify-end">
                      <button type="button" onClick={() => setCsatState("submitted")} className="text-2xs text-muted-foreground hover:text-foreground">Omitir</button>
                      <button type="button" onClick={() => setCsatState("submitted")} className="text-2xs px-2.5 py-1 rounded text-white" style={{ backgroundColor: primaryColor }}>Enviar valoración</button>
                    </div>
                  </div>
                )}
                {enableCsat && csatState === "submitted" && (
                  <div className="border-t border-border bg-muted/40 px-3 py-3 shrink-0 flex flex-col items-center gap-1.5">
                    <p className="text-xs font-medium text-foreground">
                      ¡Gracias por su valoración!
                    </p>
                    <button
                      type="button"
                      onClick={resetConversation}
                      className="text-2xs px-2.5 py-1 rounded border border-border hover:bg-muted-foreground/10 text-foreground"
                    >
                      Nueva conversación
                    </button>
                  </div>
                )}

                {/* Quick suggestions */}
                {showSuggestions && csatState === "hidden" && escalState === "hidden" && (
                  <div className="border-t border-border bg-background px-2.5 pt-2 pb-1.5 shrink-0 flex flex-wrap gap-1">
                    {suggestions.slice(0, 3).map((s, i) => (
                      <button
                        key={i}
                        onClick={() => handleSend(s)}
                        className="text-3xs px-2.5 py-1 rounded-full border border-border bg-background hover:bg-muted transition-colors text-foreground"
                      >
                        {s}
                      </button>
                    ))}
                  </div>
                )}

                {/* Input bar — estilo "pill" (paridad con el widget). */}
                {csatState === "hidden" && (
                  <div className={`bg-background px-2.5 py-2.5 shrink-0 ${showSuggestions ? "" : "border-t border-border"}`}>
                    <div className="flex gap-1.5 items-center">
                      <input
                        className="flex-1 h-9 bg-muted rounded-full px-4 text-xs outline-none border border-transparent focus:border-primary placeholder:text-muted-foreground transition-colors"
                        placeholder="Escribe un mensaje..."
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onKeyDown={(e) =>
                          e.key === "Enter" && !e.shiftKey && handleSend()
                        }
                        disabled={loading}
                      />
                      <button
                        onClick={() => handleSend()}
                        disabled={loading || !input.trim()}
                        className="w-9 h-9 rounded-full flex items-center justify-center shrink-0 text-white disabled:opacity-40 transition-opacity"
                        style={{ backgroundColor: primaryColor }}
                      >
                        {loading ? (
                          <Loader2 className="w-3.5 h-3.5 animate-spin" />
                        ) : (
                          <Send className="w-3.5 h-3.5" />
                        )}
                      </button>
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Launcher row: label + button. Oculto en mobile cuando el
                chat ya está abierto (ahí el botón "minimizar" vive dentro
                del propio header del chat, ver arriba). */}
            <div className={`items-center gap-2 self-center md:self-auto ${widgetOpen ? "hidden md:flex" : "flex"}`}>
              {!widgetOpen && launcherLabel && (
                <div className="bg-white text-slate-800 border border-slate-200 rounded-full shadow-md px-3 py-1.5 text-xs font-medium max-w-[60vw] md:max-w-[200px] truncate">
                  {launcherLabel}
                </div>
              )}
              <button
                type="button"
                onClick={() => setWidgetOpen((o) => !o)}
                className="w-12 h-12 rounded-full shadow-xl flex items-center justify-center text-white transition-transform hover:scale-105 active:scale-95"
                style={{ backgroundColor: primaryColor }}
                title={widgetOpen ? "Minimizar chat" : "Abrir chat"}
              >
                {widgetOpen ? (
                  <X className="w-5 h-5" />
                ) : logoUrl ? (
                  <img
                    src={logoUrl}
                    alt=""
                    className="w-7 h-7 rounded-full object-cover"
                  />
                ) : (
                  <Bot className="w-5 h-5" />
                )}
              </button>
            </div>
          </div>
        </div>

        {/* ── Right: debug panel ── */}
        <div className="w-full md:w-[272px] shrink-0 border-t md:border-t-0 md:border-l border-border bg-background flex flex-col overflow-hidden max-h-[320px] md:max-h-none">
          {/* Panel header */}
          <div className="px-4 py-3 border-b border-border shrink-0">
            <p className="text-xs font-semibold text-foreground">
              Panel de diagnóstico
            </p>
            <p className="text-2xs text-muted-foreground mt-0.5">
              {mode === "draft"
                ? "Fuentes: pendientes y aprobadas"
                : "Fuentes: solo aprobadas"}
            </p>
          </div>

          {/* Scrollable content */}
          <div className="flex-1 overflow-y-auto">
            {/* Empty state */}
            {!meta && lastSources.length === 0 && (
              <div className="flex flex-col items-center justify-center gap-3 px-6 py-10 text-center h-full">
                <MessageSquare className="w-9 h-9 text-muted-foreground/20" />
                <p className="text-2xs text-muted-foreground leading-relaxed">
                  Envía un mensaje para ver el diagnóstico de la respuesta: proveedor, latencia y fuentes RAG consultadas.
                </p>
              </div>
            )}

            {/* Response metadata */}
            {meta && (
              <div className="p-4 border-b border-border">
                <p className="text-3xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                  Última respuesta
                </p>
                <div className="space-y-2.5">
                  {(meta.provider || meta.model) && (
                    <div className="flex items-start gap-2">
                      <Zap className="w-3.5 h-3.5 text-muted-foreground mt-0.5 shrink-0" />
                      <div className="min-w-0">
                        {meta.provider && (
                          <p className="text-xs font-medium text-foreground truncate">
                            {meta.provider}
                          </p>
                        )}
                        {meta.model && (
                          <p className="text-2xs text-muted-foreground truncate">
                            {meta.model}
                          </p>
                        )}
                      </div>
                    </div>
                  )}
                  {meta.latency != null && (
                    <div className="flex items-center gap-2">
                      <span
                        className={`inline-flex items-center px-2 py-0.5 rounded-full text-2xs font-mono font-semibold ${
                          meta.latency < 2000
                            ? "bg-success/10 text-success"
                            : meta.latency < 5000
                              ? "bg-warning/10 text-warning"
                              : "bg-destructive/10 text-destructive"
                        }`}
                      >
                        {meta.latency < 1000
                          ? `${meta.latency} ms`
                          : `${(meta.latency / 1000).toFixed(1)} s`}
                      </span>
                      <span className="text-2xs text-muted-foreground">
                        latencia total
                      </span>
                    </div>
                  )}
                </div>
              </div>
            )}

            {/* RAG sources */}
            {lastSources.length > 0 && (
              <div className="p-4">
                <p className="text-3xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                  Fuentes RAG · {lastSources.length}
                </p>
                <div className="space-y-2">
                  {lastSources.map((s, i) => (
                    <SourceCard
                      key={i}
                      source={s.source}
                      score={s.score}
                      text={s.text}
                      index={i}
                    />
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Footer */}
          <div className="p-3 border-t border-border shrink-0">
            <button
              type="button"
              onClick={resetConversation}
              className="w-full flex items-center justify-center gap-1.5 py-1.5 text-2xs text-muted-foreground hover:text-foreground border border-border rounded-md hover:bg-muted transition-colors"
            >
              <RotateCcw className="w-3 h-3" />
              Nueva conversación
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
