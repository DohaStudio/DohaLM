import src.cli.main as cli
from src.cli.main import main
from src.runtime.paths import repository_root


def test_environment_cli_cpu_smoke(capsys):
    code = main(["environment", "--json"])
    output = capsys.readouterr().out
    assert code == 0
    assert '"python_supported": true' in output
    assert '"cpu_smoke"' in output


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
