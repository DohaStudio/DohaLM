"use client";

import { useEffect, useRef } from "react";
import { MessageBubble } from "./message-bubble";
import type { ClientMessage } from "@/lib/types";

export function MessageList({ messages }: { messages: ClientMessage[] }) {
  const endRef = useRef<HTMLDivElement>(null);
  useEffect(() => endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" }), [messages]);
  return (
    <section className="message-list" aria-live="polite" aria-busy={messages.some((item) => item.status === "streaming")}>
      {messages.map((message) => <MessageBubble key={message.id} message={message} />)}
      <div ref={endRef} />
    </section>
  );
}
