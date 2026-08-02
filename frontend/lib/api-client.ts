import { API_BASE_URL } from "./constants";
import { backendError, DohaAPIError, toDohaError } from "./errors";
import { consumeSSE } from "./sse";
import type {
  ChatRequest,
  ChatResponse,
  HealthResponse,
  ModelListResponse,
  ReadinessResponse,
  StreamEvent,
} from "./types";

type RequestOptions = { signal?: AbortSignal };
type StreamCallbacks = {
  onStart?: (data: Extract<StreamEvent, { event: "start" }>["data"]) => void;
  onDelta?: (data: Extract<StreamEvent, { event: "delta" }>["data"]) => void;
  onDone?: (data: Extract<StreamEvent, { event: "done" }>["data"]) => void;
  onError?: (data: Extract<StreamEvent, { event: "error" }>["data"]) => void;
};

async function requestJSON<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...init.headers },
    });
  } catch (error) {
    throw toDohaError(error);
  }
  const requestId = response.headers.get("X-Request-ID") ?? undefined;
  let payload: unknown;
  try {
    payload = await response.json();
  } catch {
    throw new DohaAPIError("UNKNOWN_ERROR", "API 응답을 해석하지 못했습니다.", requestId, response.status);
  }
  if (!response.ok) throw backendError(payload, response.status, requestId);
  return payload as T;
}

export const getHealth = (options: RequestOptions = {}) =>
  requestJSON<HealthResponse>("/health", { signal: options.signal });

export const getReadiness = (options: RequestOptions = {}) =>
  requestJSON<ReadinessResponse>("/ready", { signal: options.signal });

export const getModels = (options: RequestOptions = {}) =>
  requestJSON<ModelListResponse>("/api/v1/models", { signal: options.signal });

export const sendChat = (body: ChatRequest, options: RequestOptions = {}) =>
  requestJSON<ChatResponse>("/api/v1/chat", {
    method: "POST",
    body: JSON.stringify(body),
    signal: options.signal,
  });

export async function streamChat(
  body: ChatRequest,
  callbacks: StreamCallbacks,
  options: RequestOptions = {},
): Promise<void> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/v1/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal: options.signal,
    });
  } catch (error) {
    throw toDohaError(error);
  }
  const requestId = response.headers.get("X-Request-ID") ?? undefined;
  if (!response.ok) {
    const payload = await response.json().catch(() => ({}));
    throw backendError(payload, response.status, requestId);
  }
  if (!response.body) {
    throw new DohaAPIError("STREAM_FAILED", "스트리밍 응답 본문이 없습니다.", requestId);
  }
  let streamError: DohaAPIError | undefined;
  await consumeSSE(response.body, {
    ...callbacks,
    onError(data) {
      callbacks.onError?.(data);
      streamError = new DohaAPIError(data.code, data.message, data.request_id);
    },
  });
  if (streamError) throw streamError;
}
