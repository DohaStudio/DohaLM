import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { EmptyState } from "@/components/chat/empty-state";
import { MessageBubble } from "@/components/chat/message-bubble";
import { MessageComposer } from "@/components/chat/message-composer";
import { ModelStatus } from "@/components/model/model-status";

describe("chat UI", () => {
  it("renders empty-state suggestions without auto-sending", () => {
    const select = vi.fn();
    render(<EmptyState onSelect={select} />);
    fireEvent.click(screen.getByRole("button", { name: /DohaLM 프로젝트/ }));
    expect(select).toHaveBeenCalledOnce();
    expect(screen.getByText(/로컬 모델과 안전하게 대화/)).toBeInTheDocument();
  });

  it("distinguishes online provider status", () => {
    render(<ModelStatus loading={false} online readiness={{ status: "ready", provider: { name: "mock", model_id: "dohalm-mock-v1", status: "ready" } }} models={[]} />);
    expect(screen.getByText("mock")).toBeInTheDocument();
    expect(screen.getByText("dohalm-mock-v1")).toBeInTheDocument();
  });

  it("blocks blank input, sends on Enter, and preserves Shift+Enter", () => {
    const send = vi.fn();
    const change = vi.fn();
    const { rerender } = render(<MessageComposer busy={false} draft=" " onDraftChange={change} onSend={send} onStop={vi.fn()} />);
    expect(screen.getByRole("button", { name: "메시지 전송" })).toBeDisabled();
    rerender(<MessageComposer busy={false} draft="질문" onDraftChange={change} onSend={send} onStop={vi.fn()} />);
    fireEvent.keyDown(screen.getByLabelText("메시지 입력"), { key: "Enter", shiftKey: true });
    expect(send).not.toHaveBeenCalled();
    fireEvent.keyDown(screen.getByLabelText("메시지 입력"), { key: "Enter" });
    expect(send).toHaveBeenCalledOnce();
  });

  it("shows streaming, error request ID, and cancellation states as text", () => {
    const createdAt = new Date().toISOString();
    const { rerender } = render(<MessageBubble message={{ id: "1", role: "assistant", content: "", status: "streaming", createdAt }} />);
    expect(screen.getByRole("status", { name: "답변 생성 중" })).toBeInTheDocument();
    rerender(<MessageBubble message={{ id: "1", role: "assistant", content: "부분", status: "error", requestId: "req_safe", createdAt }} />);
    expect(screen.getByText("Request ID: req_safe")).toBeInTheDocument();
    rerender(<MessageBubble message={{ id: "1", role: "assistant", content: "부분", status: "cancelled", createdAt }} />);
    expect(screen.getByText(/사용자가 생성을 중단/)).toBeInTheDocument();
  });
});
