/**
 * SSE streaming client for the chatbot API.
 *
 * The backend uses POST + StreamingResponse (not standard EventSource GET),
 * so we consume the stream via fetch + ReadableStream.
 *
 * SSE event format from backend:
 *   data: {"type":"sources","sources":[...]}
 *   data: {"type":"token","content":"..."}
 *   data: {"type":"error","message":"..."}
 *   data: {"type":"done"}
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

  if (!resp.ok || !resp.body) {
    callbacks.onError(SERVICE_UNAVAILABLE_MESSAGE);
    return;
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });

      // Split on newlines; keep the last incomplete line in the buffer
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (!line.startsWith("data: ")) continue;
        const raw = line.slice(6).trim();
        if (!raw) continue;

        let event: Record<string, unknown>;
        try {
          event = JSON.parse(raw);
        } catch {
          continue;
        }

        switch (event.type) {
          case "sources":
            callbacks.onSources((event.sources as SourceChunk[]) ?? []);
            break;
          case "token":
            callbacks.onToken((event.content as string) ?? "");
            break;
          case "error":
            callbacks.onError(event.message as string);
            break;
          case "done":
            callbacks.onDone(
              event.message_id as string | undefined,
              event.conversation_id as string | undefined,
              event.escalation_prompt as boolean | undefined,
            );
            return;
        }
      }
    }
  } catch (err) {
    if ((err as Error).name !== "AbortError") {
      callbacks.onError(SERVICE_UNAVAILABLE_MESSAGE);
    }
  } finally {
    reader.releaseLock();
  }
}
