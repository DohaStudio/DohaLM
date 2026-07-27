"""Reproducible, privacy-preserving evaluation framework."""

from .artifacts import ArtifactRegistry, EvaluationArtifact
from .benchmarks import BenchmarkAdapter, BenchmarkRegistration
from .config import EvaluationConfig, EvaluationError
from .comparison import ARTIFACT_ORDER, publish_quick_comparison
from .datasets import IndexedSubset, deterministic_indices
from .metrics import generation_statistics, prefix_metrics, safe_perplexity
from .runner import publish_failure, run_evaluation

__all__ = [
    "ArtifactRegistry", "BenchmarkAdapter", "BenchmarkRegistration", "EvaluationArtifact", "EvaluationConfig", "EvaluationError",
    "ARTIFACT_ORDER", "IndexedSubset", "deterministic_indices", "generation_statistics", "prefix_metrics",
    "publish_quick_comparison",
    "publish_failure", "run_evaluation", "safe_perplexity",
]
