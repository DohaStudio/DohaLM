import type { GenerationSettings } from "@/lib/types";

type Props = { value: GenerationSettings; disabled: boolean; onChange: (value: GenerationSettings) => void };

export function GenerationSettingsPanel({ value, disabled, onChange }: Props) {
  const field = (key: keyof GenerationSettings, label: string, min: number, max: number, step: number) => (
    <label>
      <span>{label}</span>
      <input
        type="number"
        value={value[key] ?? ""}
        min={min}
        max={max}
        step={step}
        disabled={disabled}
        onChange={(event) => onChange({ ...value, [key]: Number(event.target.value) })}
      />
    </label>
  );
  return (
    <details className="generation-settings">
      <summary>생성 설정 <span>MockProvider에서는 응답 내용에 반영되지 않을 수 있습니다.</span></summary>
      <div className="settings-grid">
        {field("max_new_tokens", "최대 토큰", 1, 1024, 1)}
        {field("temperature", "Temperature", 0, 2, 0.1)}
        {field("top_p", "Top P", 0.01, 1, 0.01)}
        {field("repetition_penalty", "반복 페널티", 0.5, 2, 0.05)}
      </div>
    </details>
  );
}
