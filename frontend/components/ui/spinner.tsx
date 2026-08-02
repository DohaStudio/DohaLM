export function Spinner({ label = "처리 중" }: { label?: string }) {
  return <span className="spinner" role="status" aria-label={label} />;
}
