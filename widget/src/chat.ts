/**
 * Chat client for the chatbot API.
 *
 * The backend responds with a single complete JSON message (no streaming) —
 * the caller shows a "typing..." indicator while awaiting this response, then
 * renders the full message at once (similar to WhatsApp/Messenger, not a
 * token-by-token typewriter effect).
 */

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
  "En este momento el asistente no está disponible. Por favor, inténtalo más tarde.";

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
  let resp: Response;
  try {
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (apiKey) headers["X-Widget-Key"] = apiKey;
    resp = await fetch(`${apiUrl}/api/v1/widget/public/chat`, {
      method: "POST",
      headers,
      body: JSON.stringify({
        question,
        source_ids: sourceIds,
        messages: history ?? [],
        session_id: sessionId ?? null,
      }),
      signal,
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") return;
    callbacks.onError(SERVICE_UNAVAILABLE_MESSAGE);
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
}
