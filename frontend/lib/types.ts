export type ChatRole = "system" | "user" | "assistant";
export type MessageStatus = "complete" | "streaming" | "error" | "cancelled";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export interface ClientMessage extends ChatMessage {
  id: string;
  status: MessageStatus;
  createdAt: string;
  requestId?: string;
}

export interface GenerationSettings {
  max_new_tokens: number;
  temperature: number;
  top_p: number;
  repetition_penalty: number;
  seed?: number | null;
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
}

export interface ProviderStatus {
  name: string;
  model_id: string;
  status: string;
}

export interface ReadinessResponse {
  status: string;
  provider: ProviderStatus;
}

export interface ModelInfo {
  id: string;
  provider: string;
  status: string;
  capabilities: string[];
}

export interface ModelListResponse {
  active_provider: string;
  models: ModelInfo[];
}

export interface BackendErrorBody {
  code: string;
  message: string;
  request_id: string;
  details: Array<Record<string, unknown>>;
}

export interface ChatResponse {
  id: string;
  model: string;
  provider: string;
  message: { role: "assistant"; content: string };
  finish_reason: string;
  usage: {
    prompt_tokens: number | null;
    completion_tokens: number | null;
    total_tokens: number | null;
  };
  created_at: string;
}

export interface ChatRequest {
  messages: ChatMessage[];
  generation: GenerationSettings;
}

export type StreamEvent =
  | { event: "start"; data: { id: string; model: string; provider: string } }
  | { event: "delta"; data: { content: string } }
  | { event: "done"; data: { finish_reason: string } }
  | { event: "error"; data: { code: string; message: string; request_id: string } };
