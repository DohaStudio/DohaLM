from __future__ import annotations

import json
from pathlib import Path

import yaml

import src.cli.main as cli


def test_data_validate_cli_is_parseable_yaml(capsys):
    code = cli.main(["data", "validate", "--config", "tests/fixtures/data/phase1-cli.yaml"])
    output = capsys.readouterr()
    assert code == 0 and not output.err
    report = yaml.safe_load(output.out)
    assert report["success"] is True and report["mode"] == "validate"


def test_data_validate_cli_json(capsys):
    code = cli.main(["data", "validate", "--config", "tests/fixtures/data/phase1-cli.yaml", "--json"])
    output = capsys.readouterr()
    assert code == 0 and json.loads(output.out)["result"]["accepted_count"] > 0


def test_data_cli_failure_is_safe(capsys):
    code = cli.main(["data", "validate", "--config", "missing.yaml"])
    output = capsys.readouterr()
    assert code == 2 and "오류:" in output.err and "Traceback" not in output.err
