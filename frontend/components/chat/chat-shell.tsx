"use client";

import { useState } from "react";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { useChat } from "@/hooks/use-chat";
import { useModelStatus } from "@/hooks/use-model-status";
import { ChatHeader } from "./chat-header";
import { EmptyState } from "./empty-state";
import { GenerationSettingsPanel } from "./generation-settings";
import { MessageComposer } from "./message-composer";
import { MessageList } from "./message-list";

export function ChatShell() {
  const model = useModelStatus();
  const chat = useChat();
  const [draft, setDraft] = useState("");

  const submit = async () => {
    const sent = await chat.send(draft);
    if (sent) {
      setDraft("");
      await model.refresh();
    }
  };
  const reset = () => {
    if (chat.messages.length && !window.confirm("현재 대화를 지우고 새로 시작할까요?")) return;
    chat.reset();
    setDraft("");
  };

  return (
    <main className="app-frame">
      <ChatHeader
        {...model}
        hasMessages={chat.messages.length > 0}
        onRefresh={() => void model.refresh()}
        onReset={reset}
      />
      <div className="chat-stage">
        {chat.messages.length === 0 ? <EmptyState onSelect={setDraft} /> : <MessageList messages={chat.messages} />}
      </div>
      <div className="interaction-dock">
        {(chat.error || model.error) && (
          <Alert>
            <div>
              <strong>{chat.error?.code ?? "API 상태 오류"}</strong>
              <span>{chat.error?.message ?? model.error}</span>
              {chat.error?.requestId && <code>Request ID: {chat.error.requestId}</code>}
            </div>
            {chat.error ? <Button variant="ghost" onClick={() => void chat.retry()} disabled={chat.busy}>재시도</Button> : <Button variant="ghost" onClick={() => void model.refresh()}>다시 확인</Button>}
          </Alert>
        )}
        <GenerationSettingsPanel value={chat.settings} disabled={chat.busy} onChange={chat.setSettings} />
        <MessageComposer busy={chat.busy} draft={draft} onDraftChange={setDraft} onSend={() => void submit()} onStop={chat.stop} />
        <p className="footer-note">DohaLM은 선택된 로컬 Provider로 답변합니다. 중요한 정보는 반드시 확인하세요.</p>
      </div>
    </main>
  );
}
