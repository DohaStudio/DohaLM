import json
from types import SimpleNamespace

import yaml

import src.runtime.environment as environment


class FakeTorchVersion(str):
    pass


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
        __version__=FakeTorchVersion("2.7.1+cu118"),
        version=SimpleNamespace(cuda=FakeTorchVersion("11.8")),
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


def test_torch_version_subclass_is_normalized_and_serializable(monkeypatch):
    monkeypatch.setattr(environment, "_torch", fake_torch)
    report = environment.collect_environment()
    version = report["pytorch_version"]["value"]
    cuda_version = report["pytorch_cuda_build"]["value"]
    assert type(version) is str
    assert version == "2.7.1+cu118"
    assert type(cuda_version) is str
    assert cuda_version == "11.8"
    yaml.safe_dump(report, allow_unicode=True)
    json.dumps(report, ensure_ascii=False)


def test_unknown_environment_value_becomes_explicit_field_error(monkeypatch):
    monkeypatch.setattr(environment.platform, "machine", lambda: object())
    report = environment.collect_environment()
    assert report["machine"]["value"] is None
    assert "지원하지 않는 환경 값 타입" in report["machine"]["error"]


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


def test_real_environment_report_is_yaml_and_json_serializable():
    report = environment.collect_environment()
    yaml_report = yaml.safe_load(yaml.safe_dump(report, allow_unicode=True))
    json_report = json.loads(json.dumps(report, ensure_ascii=False))
    assert yaml_report == json_report == report
