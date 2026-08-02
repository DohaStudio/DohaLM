"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { getHealth, getModels, getReadiness } from "@/lib/api-client";
import { toDohaError } from "@/lib/errors";
import type { ModelInfo, ReadinessResponse } from "@/lib/types";

export function useModelStatus() {
  const [loading, setLoading] = useState(true);
  const [online, setOnline] = useState(false);
  const [readiness, setReadiness] = useState<ReadinessResponse | null>(null);
  const [models, setModels] = useState<ModelInfo[]>([]);
  const [error, setError] = useState<string | null>(null);
  const activeRequest = useRef<AbortController | null>(null);

  const refresh = useCallback(async () => {
    activeRequest.current?.abort();
    const controller = new AbortController();
    activeRequest.current = controller;
    setLoading(true);
    setError(null);
    try {
      await getHealth({ signal: controller.signal });
      setOnline(true);
      const modelResult = await getModels({ signal: controller.signal });
      setModels(modelResult.models);
      try {
        setReadiness(await getReadiness({ signal: controller.signal }));
      } catch (readinessError) {
        setReadiness(null);
        setError(toDohaError(readinessError).message);
      }
    } catch (requestError) {
      if (!controller.signal.aborted) {
        setOnline(false);
        setReadiness(null);
        setModels([]);
        setError(toDohaError(requestError).message);
      }
    } finally {
      if (!controller.signal.aborted) setLoading(false);
    }
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => void refresh(), 0);
    return () => {
      window.clearTimeout(timer);
      activeRequest.current?.abort();
    };
  }, [refresh]);

  return { loading, online, readiness, models, error, refresh };
}
