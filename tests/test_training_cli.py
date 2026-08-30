from __future__ import annotations

import json

from _training_helpers import build_tiny_trainer, training_config

from scripts.training import (
    inspect_checkpoint,
    resume_training_smoke,
    run_training_smoke,
)


def test_training_cli_cpu_json(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("scripts.training._common.resolve_repository_path", lambda _: tmp_path / "run")
    code = run_training_smoke.main([
        "--device", "cpu", "--steps", "1", "--save-every", "1",
        "--output", "tests/output/cli", "--json",
    ])
    report = json.loads(capsys.readouterr().out)
    assert code == 0 and report["status"] == "training_smoke_complete"
    assert report["synthetic_only"] is True and report["state"]["global_step"] == 1


def test_training_cli_rejects_cpu_float16_without_traceback(capsys):
    code = run_training_smoke.main(["--device", "cpu", "--dtype", "float16", "--use-amp", "--json"])
    captured = capsys.readouterr()
    assert code == 2 and "AMP_NOT_AVAILABLE" in captured.err and "Traceback" not in captured.err


def test_checkpoint_inspection_cli_json(tmp_path, monkeypatch, capsys):
    trainer, _ = build_tiny_trainer(tmp_path / "run", config=training_config(max_steps=1, save_every=1))
    trainer.train()
    checkpoint = tmp_path / "run" / "checkpoint-1"
    monkeypatch.setattr(inspect_checkpoint, "resolve_repository_path", lambda _: checkpoint)
    assert inspect_checkpoint.main(["--checkpoint", "tests/output/x", "--json"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["status"] == "checkpoint_valid" and report["global_step"] == 1


def test_cli_error_is_concise_for_missing_checkpoint(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(inspect_checkpoint, "resolve_repository_path", lambda _: tmp_path / "missing")
    assert inspect_checkpoint.main(["--checkpoint", "tests/output/missing"]) == 2
    captured = capsys.readouterr()
    assert "오류:" in captured.err and "Traceback" not in captured.err


def test_resume_cli_continues_to_target_step(tmp_path, monkeypatch, capsys):
    run_root = tmp_path / "run"
    monkeypatch.setattr("scripts.training._common.resolve_repository_path", lambda _: run_root)
    assert run_training_smoke.main([
        "--steps", "1", "--max-steps", "2", "--save-every", "1",
        "--output", "tests/output/cli-resume", "--json",
    ]) == 0
    capsys.readouterr()
    checkpoint = run_root / "checkpoint-1"
    monkeypatch.setattr(resume_training_smoke, "resolve_repository_path", lambda _: checkpoint)
    assert resume_training_smoke.main([
        "--checkpoint", "tests/output/cli-resume/checkpoint-1", "--steps", "2", "--json",
    ]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["resumed_from_step"] == 1
    assert report["state"]["global_step"] == 2
