"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { sendChat, streamChat } from "@/lib/api-client";
import {
  DEFAULT_MAX_NEW_TOKENS,
  MAX_MESSAGE_LENGTH,
  MAX_TOTAL_MESSAGE_LENGTH,
  STREAMING_ENABLED,
} from "@/lib/constants";
import { DohaAPIError, toDohaError } from "@/lib/errors";
import type { ChatRequest, ClientMessage, GenerationSettings } from "@/lib/types";

const initialSettings: GenerationSettings = {
  max_new_tokens: DEFAULT_MAX_NEW_TOKENS,
  temperature: 0.7,
  top_p: 0.9,
  repetition_penalty: 1.05,
  seed: null,
};

const createId = () =>
  typeof crypto !== "undefined" && "randomUUID" in crypto
    ? crypto.randomUUID()
    : `msg_${Date.now()}_${Math.random().toString(16).slice(2)}`;

function updateMessage(
  values: ClientMessage[],
  id: string,
  update: (message: ClientMessage) => ClientMessage,
) {
  return values.map((message) => (message.id === id ? update(message) : message));
}

export function validGenerationSettings(value: GenerationSettings): boolean {
  return (
    Number.isInteger(value.max_new_tokens) &&
    value.max_new_tokens >= 1 &&
    value.max_new_tokens <= 1024 &&
    Number.isFinite(value.temperature) &&
    value.temperature >= 0 &&
    value.temperature <= 2 &&
    Number.isFinite(value.top_p) &&
    value.top_p > 0 &&
    value.top_p <= 1 &&
    Number.isFinite(value.repetition_penalty) &&
    value.repetition_penalty >= 0.5 &&
    value.repetition_penalty <= 2 &&
    (value.seed == null || Number.isInteger(value.seed))
  );
}

export function useChat() {
  const [messages, setMessages] = useState<ClientMessage[]>([]);
  const [settings, setSettings] = useState<GenerationSettings>(initialSettings);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<DohaAPIError | null>(null);
  const controllerRef = useRef<AbortController | null>(null);
  const lastRequestRef = useRef<{ body: ChatRequest; assistantId: string } | null>(null);

  const execute = useCallback(async (body: ChatRequest, assistantId: string) => {
    const controller = new AbortController();
    controllerRef.current = controller;
    setBusy(true);
    setError(null);
    try {
      if (STREAMING_ENABLED) {
        await streamChat(
          body,
          {
            onDelta: ({ content }) =>
              setMessages((current) =>
                updateMessage(current, assistantId, (message) => ({
                  ...message,
                  content: message.content + content,
                })),
              ),
            onDone: () =>
              setMessages((current) =>
                updateMessage(current, assistantId, (message) => ({ ...message, status: "complete" })),
              ),
            onError: ({ request_id }) =>
              setMessages((current) =>
                updateMessage(current, assistantId, (message) => ({
                  ...message,
                  status: "error",
                  requestId: request_id,
                })),
              ),
          },
          { signal: controller.signal },
        );
      } else {
        const response = await sendChat(body, { signal: controller.signal });
        setMessages((current) =>
          updateMessage(current, assistantId, (message) => ({
            ...message,
            content: response.message.content,
            status: "complete",
          })),
        );
      }
    } catch (requestError) {
      if (controller.signal.aborted) return;
      const resolved = toDohaError(requestError);
      setError(resolved);
      setMessages((current) =>
        updateMessage(current, assistantId, (message) => ({
          ...message,
          status: "error",
          requestId: resolved.requestId,
        })),
      );
    } finally {
      if (controllerRef.current === controller) controllerRef.current = null;
      setBusy(false);
    }
  }, []);

  const send = useCallback(
    async (content: string) => {
      const normalized = content.trim();
      if (busy || !normalized || normalized.length > MAX_MESSAGE_LENGTH) return false;
      if (!validGenerationSettings(settings)) {
        setError(new DohaAPIError("VALIDATION_ERROR", "생성 설정값의 허용 범위를 확인하세요."));
        return false;
      }
      const history = messages.filter(
        (message) => message.status === "complete" && message.content && message.role !== "system",
      );
      const totalLength = history.reduce((sum, message) => sum + message.content.length, 0) + normalized.length;
      if (totalLength > MAX_TOTAL_MESSAGE_LENGTH) {
        setError(new DohaAPIError("VALIDATION_ERROR", "대화 전체 길이가 32,000자를 초과합니다."));
        return false;
      }
      const now = new Date().toISOString();
      const user: ClientMessage = {
        id: createId(),
        role: "user",
        content: normalized,
        status: "complete",
        createdAt: now,
      };
      const assistant: ClientMessage = {
        id: createId(),
        role: "assistant",
        content: "",
        status: "streaming",
        createdAt: now,
      };
      const body: ChatRequest = {
        messages: [...history, user].map(({ role, content: messageContent }) => ({
          role,
          content: messageContent,
        })),
        generation: settings,
      };
      setMessages((current) => [...current, user, assistant]);
      lastRequestRef.current = { body, assistantId: assistant.id };
      await execute(body, assistant.id);
      return true;
    },
    [busy, execute, messages, settings],
  );

  const stop = useCallback(() => {
    controllerRef.current?.abort();
    controllerRef.current = null;
    setBusy(false);
    setMessages((current) =>
      current.map((message) =>
        message.status === "streaming" ? { ...message, status: "cancelled" } : message,
      ),
    );
  }, []);

  const retry = useCallback(async () => {
    if (busy || !lastRequestRef.current) return;
    const { body, assistantId } = lastRequestRef.current;
    setMessages((current) =>
      updateMessage(current, assistantId, (message) => ({
        ...message,
        content: "",
        status: "streaming",
        requestId: undefined,
      })),
    );
    await execute(body, assistantId);
  }, [busy, execute]);

  const reset = useCallback(() => {
    stop();
    setMessages([]);
    setError(null);
    lastRequestRef.current = null;
  }, [stop]);

  useEffect(() => () => controllerRef.current?.abort(), []);

  return { messages, settings, setSettings, busy, error, send, stop, retry, reset };
}
