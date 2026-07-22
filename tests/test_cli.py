import json

import yaml

import src.cli.main as cli
from src.cli.main import main
from src.runtime.paths import repository_root


def test_environment_cli_yaml_output(capsys):
    code = main(["environment"])
    captured = capsys.readouterr()
    parsed = yaml.safe_load(captured.out)
    assert code == 0
    assert "Traceback" not in captured.err
    assert parsed["environment"]["pytorch_version"]["value"]
    assert parsed["cpu_smoke"]["success"] is True


def test_environment_cli_json_output(capsys):
    code = main(["environment", "--json"])
    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert code == 0
    assert "Traceback" not in captured.err
    assert parsed["python_supported"] is True
    assert parsed["environment"]["pytorch_version"]["value"]


def test_environment_cli_preserves_korean_output(monkeypatch, capsys):
    report = {
        "os": {"value": "한글 환경", "error": None},
        "python_version": {"value": "3.12.5", "error": None},
        "pytorch_version": {"value": "2.7.1+cu118", "error": None},
        "git_commit": {"value": "abc", "error": None},
        "git_branch": {"value": "테스트", "error": None},
        "git_dirty": {"value": False, "error": None},
    }
    monkeypatch.setattr(cli, "collect_environment", lambda: report)
    monkeypatch.setattr(cli, "cpu_smoke_test", lambda: {"success": True, "error": None})
    assert main(["environment"]) == 0
    parsed = yaml.safe_load(capsys.readouterr().out)
    assert parsed["environment"]["os"]["value"] == "한글 환경"


def test_environment_cli_cuda_smoke_yaml_and_json(capsys):
    for arguments, loader in (
        (["environment", "--cuda-smoke"], yaml.safe_load),
        (["environment", "--cuda-smoke", "--json"], json.loads),
    ):
        code = main(arguments)
        captured = capsys.readouterr()
        parsed = loader(captured.out)
        assert code in {0, 2}
        assert "Traceback" not in captured.err
        assert "cuda_smoke" in parsed
        if parsed["environment"]["cuda_available"]["value"]:
            assert code == 0
            assert parsed["cuda_smoke"]["success"] is True


def test_environment_cli_serialization_error_is_concise(monkeypatch, capsys):
    report = {
        field: {"value": "ok", "error": None}
        for field in (
            "os",
            "python_version",
            "pytorch_version",
            "git_commit",
            "git_branch",
            "git_dirty",
        )
    }
    report["unsupported"] = {"value": object(), "error": None}
    monkeypatch.setattr(cli, "collect_environment", lambda: report)
    monkeypatch.setattr(cli, "cpu_smoke_test", lambda: {"success": True, "error": None})
    assert main(["environment"]) == 2
    captured = capsys.readouterr()
    assert "직렬화할 수 없습니다" in captured.err
    assert "Traceback" not in captured.err


def test_environment_cli_returns_failure_for_required_probe_error(monkeypatch, capsys):
    report = {
        field: {"value": "ok", "error": None}
        for field in ("os", "python_version", "pytorch_version", "git_commit", "git_branch", "git_dirty")
    }
    report["pytorch_version"] = {"value": None, "error": "PyTorch 없음"}
    monkeypatch.setattr(cli, "collect_environment", lambda: report)
    assert main(["environment", "--json"]) == 2
    assert '"diagnostic_success": false' in capsys.readouterr().out


def test_tiny_validation_cli_succeeds(capsys):
    code = main(["config", "validate"])
    output = capsys.readouterr().out
    assert code == 0
    assert "valid: true" in output


def test_incomplete_run_validation_cli_fails(capsys):
    code = main(
        [
            "config",
            "validate",
            "--run",
            str(repository_root() / "configs" / "pretrain.yaml"),
        ]
    )
    error = capsys.readouterr().err
    assert code == 2
    assert "실행 전에 값을 확정" in error


def test_resolved_config_cli_can_show_explicit_incomplete_state(capsys):
    code = main(
        [
            "config",
            "resolve",
            "--run",
            str(repository_root() / "configs" / "pretrain.yaml"),
            "--allow-incomplete",
        ]
    )
    output = capsys.readouterr().out
    assert code == 0
    assert "expected_parameter_count: 16889856" in output
    assert "micro_batch: null" in output


def test_small_validation_cli_fails(capsys):
    code = main(
        [
            "config",
            "validate",
            "--model",
            str(repository_root() / "configs" / "small.yaml"),
        ]
    )
    error = capsys.readouterr().err
    assert code == 2
    assert "비활성화" in error


def test_paths_cli_succeeds_from_different_cwd(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    code = main(["paths", "--json"])
    output = capsys.readouterr().out
    assert code == 0
    assert '"tracked_artifact_violations": []' in output
