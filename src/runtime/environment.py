"""민감 정보를 제외한 읽기 전용 실행 환경 진단."""

from __future__ import annotations

import importlib
import platform
import subprocess
import sys
from pathlib import Path
from typing import Any, Callable

from .paths import repository_root


def _field(probe: Callable[[], Any]) -> dict[str, Any]:
    try:
        return {"value": probe(), "error": None}
    except Exception as exc:  # 개별 진단 실패가 전체 보고를 막지 않게 한다.
        return {"value": None, "error": f"{type(exc).__name__}: {exc}"}


def _command(args: list[str], cwd: Path | None = None) -> str:
    result = subprocess.run(
        args,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip() or f"종료 코드 {result.returncode}"
        raise RuntimeError(detail)
    return result.stdout.strip()


def _torch():
    return importlib.import_module("torch")


def collect_environment(root: str | Path | None = None) -> dict[str, dict[str, Any]]:
    base = repository_root(root)
    probes: dict[str, Callable[[], Any]] = {
        "os": platform.platform,
        "machine": platform.machine,
        "python_version": platform.python_version,
        "pytorch_version": lambda: _torch().__version__,
        "pytorch_cuda_build": lambda: _torch().version.cuda,
        "cuda_available": lambda: _torch().cuda.is_available(),
        "cuda_device_count": lambda: _torch().cuda.device_count(),
        "gpu_name": lambda: _torch().cuda.get_device_name(0),
        "gpu_total_memory_mib": lambda: round(
            _torch().cuda.get_device_properties(0).total_memory / (1024**2)
        ),
        "cudnn_version": lambda: _torch().backends.cudnn.version(),
        "default_dtype": lambda: str(_torch().get_default_dtype()),
        "nvidia_driver_version": lambda: _command(
            ["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"], base
        ).splitlines()[0],
        "cuda_toolkit_compiler": lambda: _command(["nvcc", "--version"], base).splitlines()[-1],
        "git_commit": lambda: _command(["git", "rev-parse", "HEAD"], base),
        "git_branch": lambda: _command(["git", "branch", "--show-current"], base),
        "git_dirty": lambda: bool(_command(["git", "status", "--porcelain"], base)),
    }
    return {name: _field(probe) for name, probe in probes.items()}


def cuda_smoke_test() -> dict[str, Any]:
    try:
        torch = _torch()
        if not torch.cuda.is_available():
            return {"success": False, "skipped": True, "error": "CUDA를 사용할 수 없습니다."}
        tensor = torch.tensor([1.0, 2.0], device="cuda")
        result = float(tensor.sum().item())
        torch.cuda.synchronize()
        del tensor
        torch.cuda.empty_cache()
        return {"success": result == 3.0, "skipped": False, "error": None}
    except Exception as exc:
        return {"success": False, "skipped": False, "error": f"{type(exc).__name__}: {exc}"}


def cpu_smoke_test() -> dict[str, Any]:
    try:
        torch = _torch()
        tensor = torch.tensor([1.0, 2.0], device="cpu")
        result = float(tensor.sum().item())
        del tensor
        return {"success": result == 3.0, "error": None}
    except Exception as exc:
        return {"success": False, "error": f"{type(exc).__name__}: {exc}"}


def python_supported() -> bool:
    return (3, 10) <= sys.version_info[:2] < (3, 13)
