"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { MAX_MESSAGE_LENGTH } from "@/lib/constants";

type Props = {
  busy: boolean;
  draft: string;
  onDraftChange: (value: string) => void;
  onSend: () => void;
  onStop: () => void;
};

export function MessageComposer({ busy, draft, onDraftChange, onSend, onStop }: Props) {
  const [composing, setComposing] = useState(false);
  const valid = draft.trim().length > 0 && draft.length <= MAX_MESSAGE_LENGTH;
  return (
    <div className="composer">
      <label htmlFor="chat-input" className="sr-only">메시지 입력</label>
      <Textarea
        id="chat-input"
        value={draft}
        rows={3}
        maxLength={MAX_MESSAGE_LENGTH}
        placeholder="DohaLM에게 메시지를 보내세요"
        disabled={busy}
        onChange={(event) => onDraftChange(event.target.value)}
        onCompositionStart={() => setComposing(true)}
        onCompositionEnd={() => setComposing(false)}
        onKeyDown={(event) => {
          if (event.key === "Enter" && !event.shiftKey && !composing && !event.nativeEvent.isComposing) {
            event.preventDefault();
            if (valid && !busy) onSend();
          }
        }}
      />
      <div className="composer-footer">
        <span>{draft.length.toLocaleString()} / {MAX_MESSAGE_LENGTH.toLocaleString()}</span>
        {busy ? (
          <Button variant="danger" onClick={onStop} aria-label="답변 생성 중단">■ 중단</Button>
        ) : (
          <Button onClick={onSend} disabled={!valid} aria-label="메시지 전송">전송 <span aria-hidden="true">↑</span></Button>
        )}
      </div>
    </div>
  );
}
