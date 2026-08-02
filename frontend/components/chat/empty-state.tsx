const suggestions = [
  "DohaLM 프로젝트를 소개해줘",
  "한국어 언어 모델은 어떻게 학습해?",
  "현재 연결된 모델 상태를 알려줘",
];

export function EmptyState({ onSelect }: { onSelect: (value: string) => void }) {
  return (
    <section className="empty-state">
      <span className="eyebrow">DEVELOPMENT PREVIEW</span>
      <h2>한국어를 위한<br /><span>작은 언어 모델.</span></h2>
      <p>현재 MockProvider 기반 개발 모드입니다. 실제 모델 weight는 아직 연결되지 않았습니다.</p>
      <div className="suggestion-grid" aria-label="예시 질문">
        {suggestions.map((suggestion, index) => (
          <button key={suggestion} type="button" onClick={() => onSelect(suggestion)}>
            <span>0{index + 1}</span>{suggestion}<b aria-hidden="true">↗</b>
          </button>
        ))}
      </div>
    </section>
  );
}
