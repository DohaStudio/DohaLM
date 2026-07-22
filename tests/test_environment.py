from types import SimpleNamespace

import src.runtime.environment as environment


class FakeCuda:
    def is_available(self):
        return False

    def device_count(self):
        return 0

    def get_device_name(self, index):
        raise RuntimeError("CUDA 없음")

    def get_device_properties(self, index):
        raise RuntimeError("CUDA 없음")


def fake_torch():
    return SimpleNamespace(
        __version__="test",
        version=SimpleNamespace(cuda=None),
        cuda=FakeCuda(),
        backends=SimpleNamespace(cudnn=SimpleNamespace(version=lambda: None)),
        get_default_dtype=lambda: "torch.float32",
    )


def test_cpu_environment_returns_explicit_cuda_result(monkeypatch):
    monkeypatch.setattr(environment, "_torch", fake_torch)
    report = environment.collect_environment()
    assert report["cuda_available"] == {"value": False, "error": None}
    assert report["gpu_name"]["value"] is None
    assert report["gpu_name"]["error"] is not None


def test_cuda_smoke_is_skipped_without_cuda(monkeypatch):
    monkeypatch.setattr(environment, "_torch", fake_torch)
    result = environment.cuda_smoke_test()
    assert result["success"] is False
    assert result["skipped"] is True


def test_cpu_smoke_uses_real_pytorch_cpu_tensor():
    result = environment.cpu_smoke_test()
    assert result == {"success": True, "error": None}


def test_git_collection_failure_is_field_local(monkeypatch):
    original = environment._command

    def fail_git(args, cwd=None):
        if args[0] == "git":
            raise RuntimeError("git unavailable")
        return original(args, cwd)

    monkeypatch.setattr(environment, "_command", fail_git)
    report = environment.collect_environment()
    assert report["python_version"]["value"]
    assert "git unavailable" in report["git_commit"]["error"]
    assert "git unavailable" in report["git_branch"]["error"]
    assert "git unavailable" in report["git_dirty"]["error"]


def test_environment_report_omits_sensitive_identity_fields():
    report = environment.collect_environment()
    assert "username" not in report
    assert "hostname" not in report
    assert "python_executable" not in report
