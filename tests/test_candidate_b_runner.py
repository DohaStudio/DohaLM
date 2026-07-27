from __future__ import annotations

from pathlib import Path

from scripts.training import run_candidate_b as cli


RESOLVED = "configs/candidate-b-resolved.example.yaml"


def test_default_mode_is_inspect_and_never_runs_training(monkeypatch, capsys) -> None:
    called = False
    def forbidden(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("training must not run")
    monkeypatch.setattr(cli, "run_candidate_b", forbidden)
    code = cli.main(["inspect", "--resolved-config", RESOLVED, "--json"])
    assert code == 0
    assert called is False
    assert '"execution_allowed": false' in capsys.readouterr().out


def test_validate_reports_fixed_plan_without_execute(capsys) -> None:
    code = cli.main(["validate", "--resolved-config", RESOLVED, "--json"])
    output = capsys.readouterr().out
    assert code == 0
    assert '"optimizer_step_limit": 12208' in output
    assert '"training_started": false' in output


def test_cpu_smoke_reports_zero_optimizer_steps(capsys) -> None:
    code = cli.main(["cpu-smoke", "--resolved-config", RESOLVED, "--json"])
    output = capsys.readouterr().out
    assert code == 0
    assert '"optimizer_steps": 0' in output
    assert '"actual_approval_consumed": false' in output


def test_execute_mode_requires_explicit_flag(monkeypatch) -> None:
    monkeypatch.setattr(cli, "inspect_candidate_b_readiness", lambda **_kwargs: {"execution_allowed": False, "status": "backend_blocked", "blocking_codes": []})
    assert cli.main(["execute", "--resolved-config", RESOLVED]) == 2


def test_execute_flag_is_forbidden_outside_execute_mode() -> None:
    assert cli.main(["inspect", "--execute", "--resolved-config", RESOLVED]) == 2


def test_execute_is_blocked_before_runner_when_readiness_false(monkeypatch) -> None:
    called = False
    def forbidden(**_kwargs):
        nonlocal called
        called = True
        raise AssertionError("run_candidate_b must remain unreachable")
    monkeypatch.setattr(cli, "run_candidate_b", forbidden)
    code = cli.main(["execute", "--execute", "--resolved-config", RESOLVED])
    assert code == 2
    assert called is False


def test_preflight_is_read_only_and_physical_confirmation_stays_false(monkeypatch, capsys) -> None:
    runtime = {
        "status": "runtime_read_only_inspected",
        "physical_preflight_passed": False,
        "gpu_training_started": False,
        "cuda_allocation_smoke_run": False,
    }
    monkeypatch.setattr(cli, "inspect_candidate_b_runtime", lambda: runtime)
    code = cli.main(["preflight", "--resolved-config", RESOLVED, "--json"])
    output = capsys.readouterr().out
    assert code == 0
    assert '"physical_preflight_passed": false' in output
    assert '"gpu_training_started": false' in output


def test_resolve_config_refuses_existing_output(tmp_path: Path, monkeypatch) -> None:
    output = tmp_path / "resolved.yaml"
    output.write_text("existing", encoding="utf-8")
    paths = {
        "configs/candidate-b.example.yaml": Path("configs/candidate-b.example.yaml"),
        "configs/candidate-b.local.yaml": Path("configs/candidate-b-local.example.yaml"),
        "docs/training/candidate-b-readiness.manifest.yaml": Path("docs/training/candidate-b-readiness.manifest.yaml"),
        "configs/candidate-b-resolved.yaml": output,
        "configs/candidate-b-approval.yaml": tmp_path / "approval.yaml",
        "docs/training/candidate-b-cpu-validation.manifest.yaml": Path("docs/training/candidate-b-cpu-validation.manifest.yaml"),
        "docs/training/candidate-b-output-probe.manifest.yaml": Path("docs/training/candidate-b-output-probe.manifest.yaml"),
    }
    monkeypatch.setattr(cli, "_repository_path", lambda value: paths[value])
    assert cli.main(["resolve-config"]) == 2
