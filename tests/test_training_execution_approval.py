from __future__ import annotations

import copy
import gc
import importlib.util
import pickle
import threading
import weakref
from dataclasses import replace
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import scripts.training.run_full_pretraining as cli
import src.training.execution_approval as boundary
import src.training.full_pretraining_backend as backend
import src.training.source_state as source_state
from src.data.checksums import checksum_value
from src.training.dataset_training_entry import (
    DatasetTrainingPermission,
    evaluate_dataset_training_entry,
)
from src.training.errors import TrainingError
from src.training.execution_approval import (
    TrainingExecutionApproval,
    TrainingExecutionRequest,
    build_training_execution_request,
    consume_training_execution_approval,
    require_training_execution_request,
)


COMMIT = "a" * 40
FINGERPRINT = "sha256:" + "1" * 64


def _publication_fixtures() -> ModuleType:
    path = Path(__file__).with_name("test_dataset_publication.py")
    spec = importlib.util.spec_from_file_location("_approval_fixtures", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("publication fixtures unavailable")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _permission(tmp_path: Path) -> DatasetTrainingPermission:
    fixtures = _publication_fixtures()
    published = fixtures.publish(tmp_path / "publication")
    manifest = published.dataset_manifest
    permission = evaluate_dataset_training_entry(
        published.dataset_version,
        manifest,
        upstream_objects=fixtures.upstream(),
        evaluated_at="2026-08-12T00:00:00Z",
        readiness_report={
            "execution_allowed": True,
            "inspection_only": True,
            "training_started": False,
            "blocking_codes": [],
        },
        expected_split_id=manifest["split_id"],
        artifact_references=manifest["object_file_artifact_refs"],
    )
    assert permission.allowed is True
    return permission


def _target(permission: DatasetTrainingPermission) -> dict[str, str]:
    return {
        "dataset_version_id": permission.dataset_version_id,
        "dataset_manifest_id": permission.dataset_manifest_id,
        "dataset_pair_fingerprint": permission.pair_fingerprint,
    }


def _report() -> dict[str, object]:
    return {
        "execution_allowed": True,
        "blocking_codes": [],
        "readiness_fingerprint": "sha256:" + "2" * 64,
        "source_commit": COMMIT,
        "source_worktree_clean": True,
    }


@pytest.fixture
def approval_context(monkeypatch, tmp_path: Path):
    permission = _permission(tmp_path)
    state = {"commit": COMMIT, "clean": True, "config": FINGERPRINT}
    config = SimpleNamespace(resume_checkpoint=None, output_dir="runs/RUN-1")
    monkeypatch.setattr(
        boundary,
        "_inspect_source_state",
        lambda: SimpleNamespace(
            commit=state["commit"], branch="develop", clean=state["clean"]
        ),
    )
    monkeypatch.setattr(boundary.FullPretrainingConfig, "from_yaml", lambda _p: config)
    monkeypatch.setattr(
        boundary, "resolve_full_pretraining_path", lambda *_a: tmp_path / "RUN-1"
    )
    monkeypatch.setattr(boundary, "file_checksum", lambda _p: state["config"])
    report = _report()

    def build() -> TrainingExecutionRequest:
        return build_training_execution_request(
            Path("config.yaml"),
            report,
            dataset_permission=permission,
            **_target(permission),
        )

    def issue(
        request: TrainingExecutionRequest,
        *,
        decision: str = "approved",
    ) -> TrainingExecutionApproval:
        return boundary._issue_training_execution_approval_from_trusted_adapter(
            request,
            dataset_permission=permission,
            decision=decision,
            authorization_id="authorization-1",
            issuer_id="issuer-1",
            approver_reference="approver-1",
            evidence_reference="evidence-1",
            request_fingerprint=request.request_fingerprint,
            issued_at="2026-08-12T12:00:00+09:00",
        )

    return SimpleNamespace(
        permission=permission,
        state=state,
        config=config,
        report=report,
        build=build,
        issue=issue,
        tmp_path=tmp_path,
    )


def _consume(context, approval, request) -> None:
    consume_training_execution_approval(
        approval,
        request,
        dataset_permission=context.permission,
        **_target(context.permission),
    )


def test_request_projection_is_exact_deterministic_and_non_mutating(
    approval_context,
) -> None:
    report_before = copy.deepcopy(approval_context.report)
    first = approval_context.build()
    second = approval_context.build()
    assert first == second and first is not second
    projection = {
        name: getattr(first, name)
        for name in (
            "schema_version",
            "action",
            "dataset_version_id",
            "dataset_manifest_id",
            "dataset_pair_fingerprint",
            "config_fingerprint",
            "readiness_fingerprint",
            "run_id",
            "output_logical_root",
            "source_commit",
            "execution_mode",
        )
    }
    assert first.request_fingerprint == checksum_value(projection)
    assert first.schema_version == 1
    assert first.action == "full_pretraining"
    assert first.run_id == "RUN-1"
    assert first.output_logical_root == "runs/RUN-1"
    assert approval_context.report == report_before


def test_request_config_target_and_source_changes_fail_closed(approval_context) -> None:
    request = approval_context.build()
    approval_context.state["config"] = "sha256:" + "3" * 64
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
        require_training_execution_request(
            request,
            Path("config.yaml"),
            approval_context.report,
            dataset_permission=approval_context.permission,
            **_target(approval_context.permission),
        )
    approval_context.state["config"] = FINGERPRINT
    wrong = _target(approval_context.permission)
    wrong["dataset_version_id"] = "other"
    with pytest.raises(
        TrainingError, match="DATASET_TRAINING_PERMISSION_TARGET_MISMATCH"
    ):
        require_training_execution_request(
            request,
            Path("config.yaml"),
            approval_context.report,
            dataset_permission=approval_context.permission,
            **wrong,
        )
    approval_context.state["commit"] = "b" * 40
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
        approval_context.build()
    approval_context.state.update(commit=COMMIT, clean=False)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
        approval_context.build()


@pytest.mark.parametrize(
    "maker", [copy.copy, copy.deepcopy, lambda value: replace(value)]
)
def test_request_copy_and_replace_have_no_provenance(approval_context, maker) -> None:
    request = approval_context.build()
    forged = maker(request)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
        require_training_execution_request(
            forged,
            Path("config.yaml"),
            approval_context.report,
            dataset_permission=approval_context.permission,
            **_target(approval_context.permission),
        )


def test_request_pickle_manual_and_field_mutation_have_no_authority(
    approval_context,
) -> None:
    request = approval_context.build()
    manual = TrainingExecutionRequest(**request.__dict__)
    for forged in (pickle.loads(pickle.dumps(request)), manual):
        with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
            require_training_execution_request(
                forged,
                Path("config.yaml"),
                approval_context.report,
                dataset_permission=approval_context.permission,
                **_target(approval_context.permission),
            )
    object.__setattr__(request, "action", "full_pretraining")
    object.__setattr__(request, "run_id", "forged")
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
        require_training_execution_request(
            request,
            Path("config.yaml"),
            approval_context.report,
            dataset_permission=approval_context.permission,
            **_target(approval_context.permission),
        )


def test_production_issuer_is_unavailable_and_denial_creates_nothing(
    approval_context,
) -> None:
    assert "issue_training_execution_approval" not in boundary.__all__
    assert not hasattr(cli, "issue_training_execution_approval")
    request = approval_context.build()
    before = len(boundary._APPROVAL_REGISTRY)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_DENIED"):
        approval_context.issue(request, decision="denied")
    assert len(boundary._APPROVAL_REGISTRY) == before


def test_approved_issuance_evidence_and_exact_instance(approval_context) -> None:
    request = approval_context.build()
    approval = approval_context.issue(request)
    assert approval.request_fingerprint == request.request_fingerprint
    assert not hasattr(approval, "decision")
    _consume(approval_context, approval, request)


def test_direct_constructor_and_all_reconstructions_are_invalid(
    approval_context,
) -> None:
    request = approval_context.build()
    original = approval_context.issue(request)
    manual = TrainingExecutionApproval(**original.__dict__)
    forged_values = (
        manual,
        copy.copy(original),
        copy.deepcopy(original),
        pickle.loads(pickle.dumps(original)),
        replace(original),
    )
    for forged in forged_values:
        with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_INVALID"):
            _consume(approval_context, forged, request)
    object.__setattr__(manual, "request_fingerprint", request.request_fingerprint)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_INVALID"):
        _consume(approval_context, manual, request)
    _consume(approval_context, original, request)


def test_mutating_exact_approval_invalidates_it(approval_context) -> None:
    request = approval_context.build()
    approval = approval_context.issue(request)
    object.__setattr__(approval, "issuer_id", "forged")
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_INVALID"):
        _consume(approval_context, approval, request)


def test_approval_registry_follows_gc(approval_context) -> None:
    request = approval_context.build()
    approval = approval_context.issue(request)
    key = id(approval)
    reference = weakref.ref(approval)
    del approval
    gc.collect()
    assert reference() is None and key not in boundary._APPROVAL_REGISTRY


def test_consume_and_revoke_terminal_matrix(approval_context) -> None:
    request = approval_context.build()
    consumed = approval_context.issue(request)
    _consume(approval_context, consumed, request)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_CONSUMED"):
        _consume(approval_context, consumed, request)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_CONSUMED"):
        boundary._revoke_training_execution_approval_from_trusted_adapter(consumed)

    revoked = approval_context.issue(request)
    boundary._revoke_training_execution_approval_from_trusted_adapter(revoked)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_REVOKED"):
        _consume(approval_context, revoked, request)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_REVOKED"):
        boundary._revoke_training_execution_approval_from_trusted_adapter(revoked)


def test_absent_mismatch_and_wrong_request_fail_closed(approval_context) -> None:
    request = approval_context.build()
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_REQUIRED"):
        _consume(approval_context, None, request)
    approval = approval_context.issue(request)
    other = approval_context.build()
    with pytest.raises(
        TrainingError, match="TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH"
    ):
        _consume(approval_context, approval, other)


def test_consume_consume_race_has_one_success(approval_context) -> None:
    request = approval_context.build()
    approval = approval_context.issue(request)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def worker() -> None:
        barrier.wait()
        try:
            _consume(approval_context, approval, request)
            outcomes.append("success")
        except TrainingError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == ["TRAINING_EXECUTION_APPROVAL_CONSUMED", "success"]


def test_consume_revoke_race_revoke_wins(approval_context, monkeypatch) -> None:
    request = approval_context.build()
    approval = approval_context.issue(request)
    checked = threading.Event()
    release = threading.Event()
    original = boundary._verified_source

    def source_check(commit: str) -> None:
        original(commit)
        checked.set()
        release.wait(timeout=5)

    monkeypatch.setattr(boundary, "_verified_source", source_check)
    outcomes: list[str] = []

    def consume() -> None:
        try:
            _consume(approval_context, approval, request)
            outcomes.append("consume-success")
        except TrainingError as exc:
            outcomes.append(exc.code)

    thread = threading.Thread(target=consume)
    thread.start()
    checked.wait(timeout=5)
    try:
        boundary._revoke_training_execution_approval_from_trusted_adapter(approval)
        outcomes.append("revoke-success")
    except TrainingError as exc:
        outcomes.append(exc.code)
    release.set()
    thread.join()
    assert sorted(outcomes) == [
        "TRAINING_EXECUTION_APPROVAL_REVOKED",
        "revoke-success",
    ]


def test_consume_revoke_race_consume_wins(approval_context, monkeypatch) -> None:
    request = approval_context.build()
    approval = approval_context.issue(request)
    start = threading.Barrier(3)
    consumed = threading.Event()
    outcomes: list[str] = []
    original = boundary._approval_record

    def ordered_record(value):
        if threading.current_thread().name == "revoke":
            consumed.wait(timeout=5)
        return original(value)

    monkeypatch.setattr(boundary, "_approval_record", ordered_record)

    def consume() -> None:
        start.wait()
        try:
            _consume(approval_context, approval, request)
            outcomes.append("consume-success")
        except TrainingError as exc:
            outcomes.append(exc.code)
        finally:
            consumed.set()

    def revoke() -> None:
        start.wait()
        try:
            boundary._revoke_training_execution_approval_from_trusted_adapter(approval)
            outcomes.append("revoke-success")
        except TrainingError as exc:
            outcomes.append(exc.code)

    threads = [
        threading.Thread(target=consume, name="consume"),
        threading.Thread(target=revoke, name="revoke"),
    ]
    for thread in threads:
        thread.start()
    start.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [
        "TRAINING_EXECUTION_APPROVAL_CONSUMED",
        "consume-success",
    ]


def test_source_drift_preserves_issued_and_restore_retries(approval_context) -> None:
    request = approval_context.build()
    approval = approval_context.issue(request)
    approval_context.state["clean"] = False
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
        _consume(approval_context, approval, request)
    assert boundary._approval_record(approval).state == "issued"
    approval_context.state["clean"] = True
    _consume(approval_context, approval, request)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_CONSUMED"):
        _consume(approval_context, approval, request)


def test_head_drift_preserves_issued(approval_context) -> None:
    request = approval_context.build()
    approval = approval_context.issue(request)
    approval_context.state["commit"] = "b" * 40
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
        _consume(approval_context, approval, request)
    assert boundary._approval_record(approval).state == "issued"


def test_valid_backend_path_stops_at_post_consume_sentinel(
    approval_context, monkeypatch
) -> None:
    request = approval_context.build()
    approval = approval_context.issue(request)
    calls: list[str] = []
    config = approval_context.config
    config.disk_budget = {"minimum_free_bytes_before_start": 0}
    monkeypatch.setattr(backend.FullPretrainingConfig, "from_yaml", lambda _p: config)
    monkeypatch.setattr(
        backend,
        "resolve_full_pretraining_path",
        lambda *_a: approval_context.tmp_path / "RUN-1",
    )
    monkeypatch.setattr(
        backend.shutil, "disk_usage", lambda _p: SimpleNamespace(free=1)
    )
    monkeypatch.setattr(
        backend, "issue_training_execution_approval", lambda _request: approval
    )
    monkeypatch.setattr(
        backend,
        "_enter_execution_boundary",
        lambda: (_ for _ in ()).throw(
            TrainingError("SYNTHETIC_EXECUTION_BOUNDARY", "stop")
        ),
    )
    for name in (
        "_lineage",
        "seed_everything",
        "TokenizedJsonlDataset",
        "DohaLMTiny",
        "Trainer",
        "evaluate_language_model",
    ):
        monkeypatch.setattr(
            backend,
            name,
            lambda *_a, _name=name, **_k: calls.append(_name),
        )
    with pytest.raises(TrainingError, match="SYNTHETIC_EXECUTION_BOUNDARY"):
        backend.run_full_pretraining(
            Path("config.yaml"),
            Path("manifest.yaml"),
            approval_context.report,
            dataset_permission=approval_context.permission,
            execution_request=request,
            **_target(approval_context.permission),
        )
    assert calls == []
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_CONSUMED"):
        _consume(approval_context, approval, request)


def test_readiness_denial_never_reaches_approval_or_execution(
    approval_context, monkeypatch
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(
        backend,
        "issue_training_execution_approval",
        lambda _request: calls.append("issuer"),
    )
    monkeypatch.setattr(
        backend,
        "consume_training_execution_approval",
        lambda *_a, **_k: calls.append("approval"),
    )
    monkeypatch.setattr(
        backend,
        "_enter_execution_boundary",
        lambda: calls.append("execution"),
    )
    with pytest.raises(TrainingError, match="FULL_PRETRAINING_EXECUTION_BLOCKED"):
        backend.run_full_pretraining(
            Path("config.yaml"),
            Path("manifest.yaml"),
            {"execution_allowed": False, "blocking_codes": ["blocked"]},
            dataset_permission=approval_context.permission,
            **_target(approval_context.permission),
        )
    assert calls == []


@pytest.mark.parametrize(
    ("case", "code"),
    (
        ("absent", "TRAINING_EXECUTION_APPROVAL_REQUIRED"),
        ("mismatch", "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH"),
        ("consumed", "TRAINING_EXECUTION_APPROVAL_CONSUMED"),
        ("revoked", "TRAINING_EXECUTION_APPROVAL_REVOKED"),
    ),
)
def test_invalid_approval_paths_have_zero_execution_side_effects(
    approval_context, monkeypatch, case: str, code: str
) -> None:
    request = approval_context.build()
    approval = None
    if case == "mismatch":
        other = approval_context.build()
        approval = approval_context.issue(other)
    elif case in {"consumed", "revoked"}:
        approval = approval_context.issue(request)
        if case == "consumed":
            _consume(approval_context, approval, request)
        else:
            boundary._revoke_training_execution_approval_from_trusted_adapter(approval)
    approval_context.config.disk_budget = {"minimum_free_bytes_before_start": 0}
    monkeypatch.setattr(
        backend.FullPretrainingConfig,
        "from_yaml",
        lambda _p: approval_context.config,
    )
    monkeypatch.setattr(
        backend,
        "resolve_full_pretraining_path",
        lambda *_a: approval_context.tmp_path / "RUN-1",
    )
    monkeypatch.setattr(
        backend.shutil, "disk_usage", lambda _p: SimpleNamespace(free=1)
    )
    monkeypatch.setattr(
        backend, "issue_training_execution_approval", lambda _request: approval
    )
    calls: list[str] = []
    for name in (
        "_enter_execution_boundary",
        "_lineage",
        "seed_everything",
        "TokenizedJsonlDataset",
        "DohaLMTiny",
        "Trainer",
        "evaluate_language_model",
    ):
        monkeypatch.setattr(
            backend,
            name,
            lambda *_a, _name=name, **_k: calls.append(_name),
        )
    with pytest.raises(TrainingError, match=code):
        backend.run_full_pretraining(
            Path("config.yaml"),
            Path("manifest.yaml"),
            approval_context.report,
            dataset_permission=approval_context.permission,
            execution_request=request,
            **_target(approval_context.permission),
        )
    assert calls == []


def test_source_state_verifier_uses_fixed_non_shell_commands(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    outputs = iter((COMMIT + "\n", "develop\n", ""))

    def run(command, **kwargs):
        calls.append({"command": command, **kwargs})
        return SimpleNamespace(returncode=0, stdout=next(outputs))

    monkeypatch.setattr(source_state.subprocess, "run", run)
    state = source_state._inspect_source_state()
    assert state.commit == COMMIT and state.branch == "develop" and state.clean
    assert [call["command"] for call in calls] == [
        ["git", "rev-parse", "HEAD"],
        ["git", "branch", "--show-current"],
        ["git", "status", "--porcelain", "--untracked-files=normal"],
    ]
    assert all(call["shell"] is False for call in calls)
