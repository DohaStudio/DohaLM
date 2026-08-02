import { afterEach, describe, expect, it, vi } from "vitest";
import { getHealth, getModels, getReadiness, sendChat, streamChat } from "@/lib/api-client";
import { DohaAPIError } from "@/lib/errors";
import type { ChatRequest } from "@/lib/types";

const request: ChatRequest = {
  messages: [{ role: "user", content: "테스트" }],
  generation: { max_new_tokens: 256, temperature: 0.7, top_p: 0.9, repetition_penalty: 1.05 },
};

function jsonResponse(value: unknown, status = 200, headers: HeadersInit = {}) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json", ...headers } });
}

afterEach(() => vi.unstubAllGlobals());

describe("API client", () => {
  it("parses health, readiness, models, and chat schemas", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(jsonResponse({ status: "ok", service: "dohalm-api", version: "0.1.0" }))
      .mockResolvedValueOnce(jsonResponse({ status: "ready", provider: { name: "mock", model_id: "dohalm-mock-v1", status: "ready" } }))
      .mockResolvedValueOnce(jsonResponse({ active_provider: "mock", models: [{ id: "dohalm-mock-v1", provider: "mock", status: "ready", capabilities: ["chat", "streaming"] }] }))
      .mockResolvedValueOnce(jsonResponse({ id: "chat_1", model: "dohalm-mock-v1", provider: "mock", message: { role: "assistant", content: "응답" }, finish_reason: "stop", usage: { prompt_tokens: null, completion_tokens: null, total_tokens: null }, created_at: "2026-08-03T00:00:00Z" }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await getHealth()).status).toBe("ok");
    expect((await getReadiness()).provider.name).toBe("mock");
    expect((await getModels()).models).toHaveLength(1);
    expect((await sendChat(request)).message.content).toBe("응답");
  });

  it("preserves structured errors and request IDs", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({ error: { code: "PROVIDER_NOT_READY", message: "not ready", request_id: "req_test", details: [] } }, 503)));
    await expect(getReadiness()).rejects.toMatchObject({ code: "PROVIDER_NOT_READY", requestId: "req_test", status: 503 });
  });

  it("maps network errors without exposing internals", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("private host path")));
    await expect(getHealth()).rejects.toMatchObject({ code: "NETWORK_ERROR", message: "API 서버에 연결할 수 없습니다." });
  });

  it("passes AbortSignal to fetch", async () => {
    const controller = new AbortController();
    const fetchMock = vi.fn().mockRejectedValue(new DOMException("aborted", "AbortError"));
    vi.stubGlobal("fetch", fetchMock);
    controller.abort();
    await expect(getHealth({ signal: controller.signal })).rejects.toBeInstanceOf(DohaAPIError);
    expect(fetchMock.mock.calls[0][1].signal).toBe(controller.signal);
  });

  it("streams deltas and a single done event", async () => {
    const bytes = new TextEncoder().encode('event: start\ndata: {"id":"1","model":"m","provider":"mock"}\n\nevent: delta\ndata: {"content":"응답"}\n\nevent: done\ndata: {"finish_reason":"stop"}\n\n');
    const response = new Response(new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); } }), { status: 200, headers: { "Content-Type": "text/event-stream" } });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response));
    const onDelta = vi.fn();
    const onDone = vi.fn();
    await streamChat(request, { onDelta, onDone });
    expect(onDelta).toHaveBeenCalledWith({ content: "응답" });
    expect(onDone).toHaveBeenCalledOnce();
  });
});
