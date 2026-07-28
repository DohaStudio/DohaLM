"""원문 비출력형 데이터 검사 공개 인터페이스."""

from .inspector import SafeDatasetInspector, guard_safe_output

__all__ = ["SafeDatasetInspector", "guard_safe_output"]
