export interface SourceChunk {
  text: string;
  source_name: string;
  score: number;
}

export interface ChatCallbacks {
  onSources: (sources: SourceChunk[]) => void;
  onToken: (token: string) => void;
  onDone: (messageId?: string, conversationId?: string, escalationPrompt?: boolean) => void;
  onError: (message: string) => void;
}

export interface ChatHistoryMessage {
  role: "user" | "assistant";
  content: string;
}

export const SERVICE_UNAVAILABLE_MESSAGE =
  "En este momento el asistente no está disponible. Por favor, inténtelo más tarde.";

export const EMPTY_RESPONSE_MESSAGE =
  "No se recibió respuesta. Por favor, vuelva a enviar su pregunta.";

export const OFFLINE_MESSAGE =
  "Parece que no hay conexión a internet. Revise su red y vuelva a intentarlo.";

export const TIMEOUT_MESSAGE =
  "El asistente está tardando más de lo normal. Por favor, vuelva a intentarlo.";

export const BUSY_MESSAGE =
  "El asistente está atendiendo muchas consultas. Espere unos segundos e inténtelo de nuevo.";

const REQUEST_TIMEOUT_MS = 45000;
const MAX_ATTEMPTS = 3;
const BASE_BACKOFF_MS = 800;
const MAX_BACKOFF_MS = 8000;

function backoffDelay(attempt: number, retryAfterSeconds?: number): number {
  if (retryAfterSeconds && retryAfterSeconds > 0) {
    return Math.min(retryAfterSeconds * 1000, MAX_BACKOFF_MS);
  }
  const exponential = Math.min(BASE_BACKOFF_MS * 2 ** attempt, MAX_BACKOFF_MS);
  return exponential / 2 + Math.random() * (exponential / 2);
}

function parseRetryAfter(resp: Response): number | undefined {
  const raw = resp.headers.get("Retry-After");
  if (!raw) return undefined;
  const seconds = Number(raw);
  return Number.isFinite(seconds) && seconds >= 0 ? seconds : undefined;
}

function wait(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) { reject(new DOMException("Aborted", "AbortError")); return; }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    function onAbort() {
      clearTimeout(timer);
      reject(new DOMException("Aborted", "AbortError"));
    }
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

interface ChatApiResponse {
  type?: string;
  message?: string;
  sources?: SourceChunk[];
  content?: string;
  message_id?: string;
  conversation_id?: string;
  escalation_prompt?: boolean;
}

export async function streamChat(
  apiUrl: string,
  question: string,
  sourceIds: string[] | null,
  callbacks: ChatCallbacks,
  signal?: AbortSignal,
  history?: ChatHistoryMessage[],
  apiKey?: string,
  sessionId?: string,
): Promise<void> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (apiKey) headers["X-Widget-Key"] = apiKey;
  const body = JSON.stringify({
    question,
    source_ids: sourceIds,
    messages: history ?? [],
    session_id: sessionId ?? null,
  });

  let lastMessage = SERVICE_UNAVAILABLE_MESSAGE;

  for (let attempt = 0; attempt < MAX_ATTEMPTS; attempt++) {
    if (signal?.aborted) return;

    if (typeof navigator !== "undefined" && navigator.onLine === false) {
      callbacks.onError(OFFLINE_MESSAGE);
      return;
    }

    const timeoutCtl = new AbortController();
    const onOuterAbort = () => timeoutCtl.abort();
    signal?.addEventListener("abort", onOuterAbort, { once: true });
    let timedOut = false;
    const timer = setTimeout(() => { timedOut = true; timeoutCtl.abort(); }, REQUEST_TIMEOUT_MS);
    const cleanup = () => {
      clearTimeout(timer);
      signal?.removeEventListener("abort", onOuterAbort);
    };

    let resp: Response;
    try {
      resp = await fetch(`${apiUrl}/api/v1/widget/public/chat`, {
        method: "POST",
        headers,
        body,
        signal: timeoutCtl.signal,
      });
    } catch (err) {
      cleanup();
      if (signal?.aborted) return;
      if ((err as Error).name === "AbortError" && !timedOut) return;

      lastMessage = timedOut ? TIMEOUT_MESSAGE : SERVICE_UNAVAILABLE_MESSAGE;
      if (attempt < MAX_ATTEMPTS - 1) {
        try { await wait(backoffDelay(attempt), signal); } catch { return; }
        continue;
      }
      callbacks.onError(lastMessage);
      return;
    }
    cleanup();

    if (resp.status === 429 || resp.status >= 500) {
      lastMessage = resp.status === 429 ? BUSY_MESSAGE : SERVICE_UNAVAILABLE_MESSAGE;
      if (attempt < MAX_ATTEMPTS - 1) {
        try { await wait(backoffDelay(attempt, parseRetryAfter(resp)), signal); } catch { return; }
        continue;
      }
      callbacks.onError(lastMessage);
      return;
    }

    if (!resp.ok) {
      callbacks.onError(SERVICE_UNAVAILABLE_MESSAGE);
      return;
    }

    let data: ChatApiResponse;
    try {
      data = await resp.json();
    } catch {
      callbacks.onError(SERVICE_UNAVAILABLE_MESSAGE);
      return;
    }

    if (data.type === "error") {
      callbacks.onError(data.message ?? SERVICE_UNAVAILABLE_MESSAGE);
      return;
    }

    callbacks.onSources(data.sources ?? []);
    callbacks.onToken(data.content ?? "");
    callbacks.onDone(data.message_id, data.conversation_id, data.escalation_prompt);
    return;
  }

  callbacks.onError(lastMessage);
}
