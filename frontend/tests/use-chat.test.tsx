import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useChat } from "@/hooks/use-chat";

function sseResponse(events: string) {
  const bytes = new TextEncoder().encode(events);
  return new Response(
    new ReadableStream({ start(controller) { controller.enqueue(bytes); controller.close(); } }),
    { status: 200, headers: { "Content-Type": "text/event-stream" } },
  );
}

function pendingFetch(_input: RequestInfo | URL, init?: RequestInit): Promise<Response> {
  return new Promise((_resolve, reject) => {
    init?.signal?.addEventListener("abort", () => reject(new DOMException("aborted", "AbortError")));
  });
}

afterEach(() => vi.unstubAllGlobals());

describe("useChat", () => {
  it("adds a user, accumulates streaming content, and completes", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(sseResponse(
      'event: delta\ndata: {"content":"안녕 "}\n\nevent: delta\ndata: {"content":"하세요"}\n\nevent: done\ndata: {"finish_reason":"stop"}\n\n',
    )));
    const { result } = renderHook(() => useChat());
    await act(async () => { await result.current.send("  질문  "); });
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[0]).toMatchObject({ role: "user", content: "질문", status: "complete" });
    expect(result.current.messages[1]).toMatchObject({ role: "assistant", content: "안녕 하세요", status: "complete" });
  });

  it("records structured errors and retries without duplicating the user", async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(sseResponse('event: error\ndata: {"code":"STREAM_FAILED","message":"failed","request_id":"req_1"}\n\n'))
      .mockResolvedValueOnce(sseResponse('event: delta\ndata: {"content":"복구"}\n\nevent: done\ndata: {"finish_reason":"stop"}\n\n'));
    vi.stubGlobal("fetch", fetchMock);
    const { result } = renderHook(() => useChat());
    await act(async () => { await result.current.send("질문"); });
    expect(result.current.messages[1]).toMatchObject({ status: "error", requestId: "req_1" });
    await act(async () => { await result.current.retry(); });
    expect(result.current.messages).toHaveLength(2);
    expect(result.current.messages[1]).toMatchObject({ content: "복구", status: "complete" });
  });

  it("aborts an active request and marks the placeholder cancelled", async () => {
    vi.stubGlobal("fetch", vi.fn(pendingFetch));
    const { result } = renderHook(() => useChat());
    act(() => { void result.current.send("질문"); });
    await waitFor(() => expect(result.current.busy).toBe(true));
    act(() => result.current.stop());
    await waitFor(() => expect(result.current.messages[1].status).toBe("cancelled"));
    expect(result.current.busy).toBe(false);
  });

  it("blocks duplicate sends while busy and resets conversation", async () => {
    vi.stubGlobal("fetch", vi.fn(pendingFetch));
    const { result } = renderHook(() => useChat());
    act(() => { void result.current.send("첫 질문"); });
    await waitFor(() => expect(result.current.busy).toBe(true));
    await act(async () => { expect(await result.current.send("두 번째")).toBe(false); });
    act(() => result.current.reset());
    expect(result.current.messages).toEqual([]);
  });
});
