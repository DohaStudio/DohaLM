import type { BackendErrorBody } from "./types";

export type FrontendErrorCode =
  | "NETWORK_ERROR"
  | "API_UNAVAILABLE"
  | "PROVIDER_NOT_READY"
  | "VALIDATION_ERROR"
  | "INFERENCE_TIMEOUT"
  | "STREAM_FAILED"
  | "UNKNOWN_ERROR";

export class DohaAPIError extends Error {
  constructor(
    public readonly code: FrontendErrorCode | string,
    message: string,
    public readonly requestId?: string,
    public readonly status?: number,
  ) {
    super(message);
    this.name = "DohaAPIError";
  }
}

export function toDohaError(error: unknown): DohaAPIError {
  if (error instanceof DohaAPIError) return error;
  if (error instanceof DOMException && error.name === "AbortError") {
    return new DohaAPIError("UNKNOWN_ERROR", "요청이 취소되었습니다.");
  }
  if (error instanceof TypeError) {
    return new DohaAPIError("NETWORK_ERROR", "API 서버에 연결할 수 없습니다.");
  }
  return new DohaAPIError("UNKNOWN_ERROR", "알 수 없는 오류가 발생했습니다.");
}

export function backendError(value: unknown, status: number, requestId?: string): DohaAPIError {
  const candidate = value as { error?: Partial<BackendErrorBody> };
  const body = candidate?.error;
  return new DohaAPIError(
    typeof body?.code === "string" ? body.code : status === 503 ? "API_UNAVAILABLE" : "UNKNOWN_ERROR",
    typeof body?.message === "string" ? body.message : "API 요청을 처리하지 못했습니다.",
    typeof body?.request_id === "string" ? body.request_id : requestId,
    status,
  );
}
