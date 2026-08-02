import { DohaAPIError } from "./errors";
import type { StreamEvent } from "./types";

type StreamHandlers = {
  onStart?: (data: Extract<StreamEvent, { event: "start" }>["data"]) => void;
  onDelta?: (data: Extract<StreamEvent, { event: "delta" }>["data"]) => void;
  onDone?: (data: Extract<StreamEvent, { event: "done" }>["data"]) => void;
  onError?: (data: Extract<StreamEvent, { event: "error" }>["data"]) => void;
};

const knownEvents = new Set(["start", "delta", "done", "error"]);

export class SSEParser {
  private buffer = "";
  private terminal = false;
  private pendingCarriageReturn = false;

  constructor(private readonly emit: (event: StreamEvent) => void) {}

  feed(chunk: string): void {
    let normalized = this.pendingCarriageReturn ? `\r${chunk}` : chunk;
    this.pendingCarriageReturn = normalized.endsWith("\r");
    if (this.pendingCarriageReturn) normalized = normalized.slice(0, -1);
    this.buffer += normalized.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
    let boundary = this.buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 2);
      this.parseBlock(block);
      boundary = this.buffer.indexOf("\n\n");
    }
  }

  finish(): void {
    if (this.pendingCarriageReturn) this.buffer += "\n";
    this.pendingCarriageReturn = false;
    if (this.buffer.trim()) this.parseBlock(this.buffer);
    this.buffer = "";
    if (!this.terminal) {
      throw new DohaAPIError("STREAM_FAILED", "스트림이 완료 이벤트 없이 종료되었습니다.");
    }
  }

  private parseBlock(block: string): void {
    if (!block.trim() || this.terminal) return;
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of block.split("\n")) {
      if (line.startsWith(":")) continue;
      const separator = line.indexOf(":");
      const field = separator < 0 ? line : line.slice(0, separator);
      let value = separator < 0 ? "" : line.slice(separator + 1);
      if (value.startsWith(" ")) value = value.slice(1);
      if (field === "event") eventName = value;
      if (field === "data") dataLines.push(value);
    }
    if (!knownEvents.has(eventName)) return;
    let data: unknown;
    try {
      data = JSON.parse(dataLines.join("\n"));
    } catch {
      throw new DohaAPIError("STREAM_FAILED", "스트림 응답을 해석하지 못했습니다.");
    }
    const event = { event: eventName, data } as StreamEvent;
    this.emit(event);
    if (event.event === "done" || event.event === "error") this.terminal = true;
  }
}

export async function consumeSSE(
  stream: ReadableStream<Uint8Array>,
  handlers: StreamHandlers,
): Promise<void> {
  const decoder = new TextDecoder("utf-8");
  const parser = new SSEParser((event) => {
    if (event.event === "start") handlers.onStart?.(event.data);
    if (event.event === "delta") handlers.onDelta?.(event.data);
    if (event.event === "done") handlers.onDone?.(event.data);
    if (event.event === "error") handlers.onError?.(event.data);
  });
  const reader = stream.getReader();
  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      parser.feed(decoder.decode(value, { stream: true }));
    }
    parser.feed(decoder.decode());
    parser.finish();
  } finally {
    reader.releaseLock();
  }
}
