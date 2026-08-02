import { Button } from "@/components/ui/button";
import { ModelStatus } from "@/components/model/model-status";
import type { ModelInfo, ReadinessResponse } from "@/lib/types";

type Props = {
  loading: boolean;
  online: boolean;
  readiness: ReadinessResponse | null;
  models: ModelInfo[];
  hasMessages: boolean;
  onRefresh: () => void;
  onReset: () => void;
};

export function ChatHeader(props: Props) {
  return (
    <header className="chat-header">
      <div className="brand-lockup">
        <div className="brand-mark" aria-hidden="true">D</div>
        <div>
          <h1>DohaLM</h1>
          <p>Korean language model lab</p>
        </div>
      </div>
      <div className="header-actions">
        <ModelStatus {...props} />
        <Button variant="ghost" onClick={props.onRefresh} aria-label="API 상태 새로고침">↻</Button>
        <Button variant="secondary" onClick={props.onReset} disabled={!props.hasMessages}>
          새 대화
        </Button>
      </div>
    </header>
  );
}
