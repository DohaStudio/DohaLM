import { Spinner } from "@/components/ui/spinner";
import type { ModelInfo, ReadinessResponse } from "@/lib/types";

type Props = {
  loading: boolean;
  online: boolean;
  readiness: ReadinessResponse | null;
  models: ModelInfo[];
};

export function ModelStatus({ loading, online, readiness, models }: Props) {
  const active = models.find((model) => model.provider === readiness?.provider.name);
  return (
    <div className="model-status" aria-live="polite">
      <span className={`status-dot ${online ? "is-online" : "is-offline"}`} aria-hidden="true" />
      {loading ? (
        <><Spinner label="API 상태 확인 중" /> 상태 확인 중</>
      ) : online && readiness ? (
        <>
          <span className="status-label">{readiness.provider.name}</span>
          <span className="status-model">{active?.id ?? readiness.provider.model_id}</span>
        </>
      ) : online ? (
        <><span className="status-label">API online</span><span className="status-model">Provider not ready</span></>
      ) : (
        <span className="status-label">API offline</span>
      )}
    </div>
  );
}
