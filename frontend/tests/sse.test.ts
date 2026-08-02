import { describe, expect, it, vi } from "vitest";
import { consumeSSE, SSEParser } from "@/lib/sse";

function streamFrom(chunks: Uint8Array[]) {
  return new ReadableStream<Uint8Array>({
    start(controller) {
      chunks.forEach((chunk) => controller.enqueue(chunk));
      controller.close();
    },
  });
}

describe("SSEParser", () => {
  it("parses start, split delta, and one terminal event", () => {
    const emit = vi.fn();
    const parser = new SSEParser(emit);
    parser.feed('event: start\ndata: {"id":"1","model":"m","provider":"mock"}\n\nevent: del');
    parser.feed('ta\ndata: {"content":"안녕"}\n\nevent: done\ndata: {"finish_reason":"stop"}\n\n');
    parser.feed('event: done\ndata: {"finish_reason":"duplicate"}\n\n');
    parser.finish();
    expect(emit.mock.calls.map(([event]) => event.event)).toEqual(["start", "delta", "done"]);
  });

  it("supports multiple data lines and ignores unknown events", () => {
    const emit = vi.fn();
    const parser = new SSEParser(emit);
    parser.feed('event: telemetry\ndata: {}\n\nevent: delta\ndata: {"content":\ndata: "A"}\n\nevent: done\ndata: {"finish_reason":"stop"}\n\n');
    parser.finish();
    expect(emit).toHaveBeenCalledTimes(2);
    expect(emit.mock.calls[0][0].data.content).toBe("A");
  });

  it("decodes Korean text split inside UTF-8 bytes", async () => {
    const encoded = new TextEncoder().encode('event: delta\ndata: {"content":"한국어"}\n\nevent: done\ndata: {"finish_reason":"stop"}\n\n');
    const delta = vi.fn();
    await consumeSSE(streamFrom([encoded.slice(0, 37), encoded.slice(37, 40), encoded.slice(40)]), {
      onDelta: delta,
    });
    expect(delta).toHaveBeenCalledWith({ content: "한국어" });
  });

  it("accepts an error as the sole terminal event", async () => {
    const bytes = new TextEncoder().encode('event: error\ndata: {"code":"STREAM_FAILED","message":"failed","request_id":"req_1"}\n\n');
    const onError = vi.fn();
    await consumeSSE(streamFrom([bytes]), { onError });
    expect(onError).toHaveBeenCalledOnce();
  });

  it("fails closed when the terminal event is missing", () => {
    const parser = new SSEParser(() => undefined);
    parser.feed('event: delta\ndata: {"content":"partial"}\n\n');
    expect(() => parser.finish()).toThrow("완료 이벤트 없이");
  });
});
