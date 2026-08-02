import { Spinner } from "@/components/ui/spinner";
import type { ClientMessage } from "@/lib/types";

export function MessageBubble({ message }: { message: ClientMessage }) {
  const label = message.role === "user" ? "나" : "DohaLM";
  return (
    <article className={`message-row message-${message.role}`} aria-label={`${label} 메시지`}>
      <div className="message-meta">
        <span>{label}</span>
        <time dateTime={message.createdAt}>
          {new Date(message.createdAt).toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" })}
        </time>
      </div>
      <div className={`message-bubble status-${message.status}`}>
        {message.content ? <p>{message.content}</p> : message.status === "streaming" ? <Spinner label="답변 생성 중" /> : null}
        {message.status === "streaming" && message.content && <span className="stream-cursor" aria-hidden="true" />}
        {message.status === "error" && <small>응답을 완료하지 못했습니다.</small>}
        {message.status === "cancelled" && <small>사용자가 생성을 중단했습니다.</small>}
        {message.requestId && <code>Request ID: {message.requestId}</code>}
      </div>
    </article>
  );
}
