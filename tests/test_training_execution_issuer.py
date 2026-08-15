from __future__ import annotations

import copy
import importlib.util
import inspect
import pickle
import threading
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import src.training.execution_approval as approval_boundary
import src.training.execution_issuer as issuer
import src.training.full_pretraining_backend as backend
from src.training.dataset_training_entry import (
    DatasetTrainingPermission,
    evaluate_dataset_training_entry,
)
from src.training.errors import TrainingError
from src.training.execution_approval import (
    TrainingExecutionApproval,
    TrainingExecutionRequest,
    build_training_execution_request,
)


COMMIT = "a" * 40
FINGERPRINT = "sha256:" + "1" * 64


def _publication_fixtures() -> ModuleType:
    path = Path(__file__).with_name("test_dataset_publication.py")
    spec = importlib.util.spec_from_file_location("_issuer_fixtures", path)
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


@pytest.fixture(autouse=True)
def isolated_issuer_state(monkeypatch):
    monkeypatch.setattr(issuer, "_ADAPTER_REGISTRATION", None)
    issuer._SUBMISSION_BINDINGS.clear()
    issuer._DECISION_PROVENANCE.clear()
    issuer._DECISION_REPLAY_KEYS.clear()
    yield
    issuer._SUBMISSION_BINDINGS.clear()
    issuer._DECISION_PROVENANCE.clear()
    issuer._DECISION_REPLAY_KEYS.clear()


@pytest.fixture(scope="module")
def published_permission(tmp_path_factory) -> DatasetTrainingPermission:
    return _permission(tmp_path_factory.mktemp("issuer-publication"))


@pytest.fixture
def issuer_context(monkeypatch, tmp_path: Path, published_permission):
    permission = published_permission
    state = {"commit": COMMIT, "clean": True, "config": FINGERPRINT}
    config = SimpleNamespace(resume_checkpoint=None, output_dir="runs/RUN-1")
    monkeypatch.setattr(
        approval_boundary,
        "_inspect_source_state",
        lambda: SimpleNamespace(
            commit=state["commit"], branch="develop", clean=state["clean"]
        ),
    )
    monkeypatch.setattr(
        approval_boundary.FullPretrainingConfig,
        "from_yaml",
        lambda _p: config,
    )
    monkeypatch.setattr(
        approval_boundary,
        "resolve_full_pretraining_path",
        lambda *_a: tmp_path / Path(config.output_dir).name,
    )
    monkeypatch.setattr(approval_boundary, "file_checksum", lambda _p: state["config"])
    report = {
        "execution_allowed": True,
        "blocking_codes": [],
        "readiness_fingerprint": "sha256:" + "2" * 64,
        "source_commit": COMMIT,
        "source_worktree_clean": True,
    }

    def build() -> TrainingExecutionRequest:
        return build_training_execution_request(
            Path("config.yaml"),
            report,
            readiness_fingerprint=report["readiness_fingerprint"],
            dataset_permission=permission,
            **_target(permission),
        )

    return SimpleNamespace(
        permission=permission,
        state=state,
        config=config,
        report=report,
        build=build,
    )


def _submission(
    request: TrainingExecutionRequest,
    *,
    authorization_id: str = "authorization-1",
    decision: issuer.TrainingExecutionIssuerDecisionValue = (
        issuer.TrainingExecutionIssuerDecisionValue.APPROVED
    ),
) -> issuer._TrainingExecutionDecisionSubmission:
    return issuer._TrainingExecutionDecisionSubmission(
        decision=decision,
        authorization_id=authorization_id,
        issuer_id="issuer-1",
        approver_reference="approver-1",
        evidence_reference="evidence-1",
        request_fingerprint=request.request_fingerprint,
        issued_at="2026-08-12T12:00:00+09:00",
    )


def _submit(capability, submission) -> None:
    issuer._submit_training_execution_decision_from_trusted_orchestrator(
        capability, submission
    )


def _prepare_backend_boundary(issuer_context, monkeypatch, tmp_path: Path) -> list[str]:
    issuer_context.config.disk_budget = {"minimum_free_bytes_before_start": 0}
    calls: list[str] = []
    monkeypatch.setattr(
        backend, "resolve_full_pretraining_path", lambda *_args: tmp_path / "RUN-1"
    )
    monkeypatch.setattr(
        backend.shutil, "disk_usage", lambda _path: SimpleNamespace(free=1)
    )
    monkeypatch.setattr(
        backend,
        "_enter_execution_boundary",
        lambda: (
            calls.append("backend")
            or (_ for _ in ()).throw(
                TrainingError("SYNTHETIC_EXECUTION_BOUNDARY", "stop")
            )
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
            lambda *_args, _name=name, **_kwargs: calls.append(_name),
        )
    return calls


def _run_backend(issuer_context, request: TrainingExecutionRequest) -> None:
    backend.run_full_pretraining(
        Path("config.yaml"),
        Path("manifest.yaml"),
        issuer_context.report,
        dataset_permission=issuer_context.permission,
        execution_request=request,
        **_target(issuer_context.permission),
    )


def test_absent_registration_is_fail_closed_and_cli_has_no_issuer(
    issuer_context,
) -> None:
    cli_source = (
        Path(__file__).parents[1] / "scripts" / "training" / "run_full_pretraining.py"
    ).read_text(encoding="utf-8")
    assert "execution_issuer" not in cli_source
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_ISSUER_UNAVAILABLE"):
        issuer.issue_training_execution_approval(issuer_context.build())
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
        issuer.issue_training_execution_approval(None)  # type: ignore[arg-type]


def test_unavailable_has_zero_mutation_then_same_request_can_be_submitted(
    issuer_context,
) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    registration = issuer._ADAPTER_REGISTRATION
    assert registration is not None
    source = registration.decision_source
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_DECISION_UNAVAILABLE"):
        issuer.issue_training_execution_approval(request)
    assert source._by_authorization == {}
    assert source._by_request == {}
    assert issuer._DECISION_PROVENANCE == {}
    assert issuer._DECISION_REPLAY_KEYS == set()
    assert approval_boundary._APPROVAL_REGISTRY == {}

    _submit(capability, _submission(request))
    approval = issuer.issue_training_execution_approval(request)
    assert type(approval) is TrainingExecutionApproval
    assert approval.authorization_id == "authorization-1"


def test_approved_and_denied_paths_are_distinct(issuer_context) -> None:
    approved = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    _submit(capability, _submission(approved))
    approval = issuer.issue_training_execution_approval(approved)
    assert approval.request_fingerprint == approved.request_fingerprint

    issuer._ADAPTER_REGISTRATION = None
    issuer._SUBMISSION_BINDINGS.clear()
    denied = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    _submit(
        capability,
        _submission(
            denied,
            authorization_id="authorization-denied",
            decision=issuer.TrainingExecutionIssuerDecisionValue.DENIED,
        ),
    )
    approval_count = len(approval_boundary._APPROVAL_REGISTRY)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_APPROVAL_DENIED"):
        issuer.issue_training_execution_approval(denied)
    assert len(approval_boundary._APPROVAL_REGISTRY) == approval_count
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_DECISION_REPLAYED"):
        issuer.issue_training_execution_approval(denied)


@pytest.mark.parametrize(
    "maker",
    [
        copy.copy,
        copy.deepcopy,
        lambda value: pickle.loads(pickle.dumps(value)),
        lambda _value: issuer._TrainingExecutionSubmissionCapability(),
    ],
)
def test_forged_submission_capabilities_have_no_authority(
    issuer_context, maker
) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    forged = maker(capability)
    with pytest.raises(
        TrainingError,
        match="TRAINING_EXECUTION_DECISION_SUBMITTER_UNAUTHORIZED",
    ):
        _submit(forged, _submission(request))


def test_capability_marker_forgery_and_second_registration_fail_closed(
    issuer_context,
) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    forged = issuer._TrainingExecutionSubmissionCapability()
    with pytest.raises(AttributeError):
        object.__setattr__(forged, "_trusted", True)
    with pytest.raises(
        TrainingError,
        match="TRAINING_EXECUTION_DECISION_SUBMITTER_UNAUTHORIZED",
    ):
        _submit(forged, _submission(request))
    assert capability is not forged
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_ISSUER_UNAUTHORIZED"):
        issuer._compose_production_training_execution_issuer()


def test_duplicate_and_conflicting_submissions_are_terminal(issuer_context) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    submission = _submission(request)
    _submit(capability, submission)
    with pytest.raises(
        TrainingError,
        match="TRAINING_EXECUTION_DECISION_SUBMISSION_REPLAYED",
    ):
        _submit(capability, submission)
    with pytest.raises(
        TrainingError,
        match="TRAINING_EXECUTION_DECISION_SUBMISSION_CONFLICT",
    ):
        _submit(
            capability,
            _submission(
                request,
                decision=issuer.TrainingExecutionIssuerDecisionValue.DENIED,
            ),
        )
    with pytest.raises(
        TrainingError,
        match="TRAINING_EXECUTION_DECISION_SUBMISSION_CONFLICT",
    ):
        _submit(
            capability,
            _submission(request, authorization_id="authorization-2"),
        )


def test_malformed_submission_has_zero_source_mutation(issuer_context) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    registration = issuer._ADAPTER_REGISTRATION
    assert registration is not None
    malformed = issuer._TrainingExecutionDecisionSubmission(
        **{
            **_submission(request).__dict__,
            "authorization_id": "",
        }
    )
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_DECISION_INVALID"):
        _submit(capability, malformed)
    assert registration.decision_source._by_authorization == {}
    assert registration.decision_source._by_request == {}


def test_same_authorization_cannot_bind_a_different_request(issuer_context) -> None:
    first = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    _submit(capability, _submission(first))
    issuer_context.config.output_dir = "runs/RUN-2"
    second = issuer_context.build()
    assert first.run_id != second.run_id
    assert first.request_fingerprint != second.request_fingerprint
    with pytest.raises(
        TrainingError,
        match="TRAINING_EXECUTION_DECISION_SUBMISSION_CONFLICT",
    ):
        _submit(capability, _submission(second))


def test_concurrent_identical_submit_has_one_winner(issuer_context) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    submission = _submission(request)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def worker() -> None:
        barrier.wait()
        try:
            _submit(capability, submission)
            outcomes.append("success")
        except TrainingError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [
        "TRAINING_EXECUTION_DECISION_SUBMISSION_REPLAYED",
        "success",
    ]


def test_concurrent_conflicting_submit_has_one_winner(issuer_context) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    submissions = (
        _submission(request, authorization_id="authorization-a"),
        _submission(
            request,
            authorization_id="authorization-b",
            decision=issuer.TrainingExecutionIssuerDecisionValue.DENIED,
        ),
    )
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def worker(submission) -> None:
        barrier.wait()
        try:
            _submit(capability, submission)
            outcomes.append("success")
        except TrainingError as exc:
            outcomes.append(exc.code)

    threads = [
        threading.Thread(target=worker, args=(submission,))
        for submission in submissions
    ]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [
        "TRAINING_EXECUTION_DECISION_SUBMISSION_CONFLICT",
        "success",
    ]


def test_concurrent_claim_has_exactly_one_success(issuer_context, monkeypatch) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    _submit(capability, _submission(request))
    barrier = threading.Barrier(3)
    outcomes: list[str] = []
    seam_calls = 0
    original_seam = issuer._issue_training_execution_approval_from_trusted_adapter

    def counted_seam(*args, **kwargs):
        nonlocal seam_calls
        seam_calls += 1
        return original_seam(*args, **kwargs)

    monkeypatch.setattr(
        issuer,
        "_issue_training_execution_approval_from_trusted_adapter",
        counted_seam,
    )

    def worker() -> None:
        barrier.wait()
        try:
            issuer.issue_training_execution_approval(request)
            outcomes.append("success")
        except TrainingError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=worker) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert sorted(outcomes) == [
        "TRAINING_EXECUTION_DECISION_REPLAYED",
        "success",
    ]
    assert seam_calls == 1


def test_submit_claim_race_is_linearizable(issuer_context) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    submission = _submission(request)
    barrier = threading.Barrier(3)
    outcomes: list[str] = []

    def submit() -> None:
        barrier.wait()
        _submit(capability, submission)
        outcomes.append("submit-success")

    def claim() -> None:
        barrier.wait()
        try:
            issuer.issue_training_execution_approval(request)
            outcomes.append("claim-success")
        except TrainingError as exc:
            outcomes.append(exc.code)

    threads = [threading.Thread(target=submit), threading.Thread(target=claim)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join()
    assert "submit-success" in outcomes
    if "TRAINING_EXECUTION_DECISION_UNAVAILABLE" in outcomes:
        assert (
            type(issuer.issue_training_execution_approval(request))
            is TrainingExecutionApproval
        )
    else:
        assert "claim-success" in outcomes


@pytest.mark.parametrize(
    "result_factory",
    [
        lambda _request: None,
        lambda _request: object(),
        lambda request: SimpleNamespace(
            decision=issuer.TrainingExecutionIssuerDecisionValue.APPROVED,
            authorization_id="authorization-duck",
            issuer_id="issuer-1",
            approver_reference="approver-1",
            evidence_reference="evidence-1",
            request_fingerprint=request.request_fingerprint,
            issued_at="2026-08-12T12:00:00+09:00",
        ),
        lambda request: issuer.TrainingExecutionIssuerDecision(
            decision="approved",  # type: ignore[arg-type]
            authorization_id="authorization-malformed",
            issuer_id="issuer-1",
            approver_reference="approver-1",
            evidence_reference="evidence-1",
            request_fingerprint=request.request_fingerprint,
            issued_at="2026-08-12T12:00:00+09:00",
        ),
        lambda _request: (_ for _ in ()).throw(RuntimeError("private")),
        lambda _request: (_ for _ in ()).throw(ValueError("private")),
        lambda _request: (_ for _ in ()).throw(
            TrainingError(
                "TRAINING_EXECUTION_DECISION_REPLAYED",
                "spoofed replay",
            )
        ),
    ],
)
def test_none_wrong_type_and_arbitrary_exception_are_invalid(
    issuer_context, monkeypatch, result_factory
) -> None:
    request = issuer_context.build()
    issuer._compose_production_training_execution_issuer()
    adapter_calls: list[TrainingExecutionRequest] = []
    seam_calls = 0
    approval_registry = dict(approval_boundary._APPROVAL_REGISTRY)
    request_snapshot = request.__dict__.copy()

    def decide(_self, bound_request):
        adapter_calls.append(bound_request)
        return result_factory(bound_request)

    def private_seam(*_args, **_kwargs):
        nonlocal seam_calls
        seam_calls += 1
        raise AssertionError("invalid decisions must not reach the issuance seam")

    monkeypatch.setattr(
        issuer.ProductionTrainingExecutionIssuerAdapter,
        "decide",
        decide,
    )
    monkeypatch.setattr(
        issuer,
        "_issue_training_execution_approval_from_trusted_adapter",
        private_seam,
    )
    with pytest.raises(TrainingError) as caught:
        issuer.issue_training_execution_approval(request)
    assert type(caught.value) is TrainingError
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_INVALID"
    assert "private" not in str(caught.value)
    assert "AttributeError" not in str(caught.value)
    assert "TypeError" not in str(caught.value)
    assert "NoneType" not in str(caught.value)
    assert adapter_calls == [request]
    assert seam_calls == 0
    assert approval_boundary._APPROVAL_REGISTRY == approval_registry
    assert request.__dict__ == request_snapshot


def test_unexpected_return_validation_exception_is_sanitized(
    issuer_context, monkeypatch
) -> None:
    request = issuer_context.build()
    issuer._compose_production_training_execution_issuer()
    decision = issuer.TrainingExecutionIssuerDecision(
        decision=issuer.TrainingExecutionIssuerDecisionValue.APPROVED,
        authorization_id="authorization-validation-error",
        issuer_id="issuer-1",
        approver_reference="approver-1",
        evidence_reference="evidence-1",
        request_fingerprint=request.request_fingerprint,
        issued_at="2026-08-12T12:00:00+09:00",
    )
    seam_calls = 0
    approval_registry = dict(approval_boundary._APPROVAL_REGISTRY)
    request_snapshot = request.__dict__.copy()

    def private_seam(*_args, **_kwargs):
        nonlocal seam_calls
        seam_calls += 1
        raise AssertionError("invalid decisions must not reach the issuance seam")

    monkeypatch.setattr(
        issuer.ProductionTrainingExecutionIssuerAdapter,
        "decide",
        lambda _self, _request: decision,
    )
    monkeypatch.setattr(
        issuer,
        "_valid_timestamp",
        lambda _value: (_ for _ in ()).throw(RuntimeError("validation-private")),
    )
    monkeypatch.setattr(
        issuer,
        "_issue_training_execution_approval_from_trusted_adapter",
        private_seam,
    )
    with pytest.raises(TrainingError) as caught:
        issuer.issue_training_execution_approval(request)
    assert type(caught.value) is TrainingError
    assert caught.value.code == "TRAINING_EXECUTION_DECISION_INVALID"
    assert "validation-private" not in str(caught.value)
    assert "RuntimeError" not in str(caught.value)
    assert seam_calls == 0
    assert approval_boundary._APPROVAL_REGISTRY == approval_registry
    assert request.__dict__ == request_snapshot


def test_adapter_base_exception_is_not_swallowed(issuer_context, monkeypatch) -> None:
    request = issuer_context.build()
    issuer._compose_production_training_execution_issuer()
    monkeypatch.setattr(
        issuer.ProductionTrainingExecutionIssuerAdapter,
        "decide",
        lambda _self, _request: (_ for _ in ()).throw(KeyboardInterrupt()),
    )
    with pytest.raises(KeyboardInterrupt):
        issuer.issue_training_execution_approval(request)


def test_unavailable_subclass_and_equal_name_exception_are_invalid(
    issuer_context, monkeypatch
) -> None:
    request = issuer_context.build()
    issuer._compose_production_training_execution_issuer()

    class UnavailableSubclass(issuer._TrainingExecutionDecisionUnavailable):
        pass

    for exception in (
        UnavailableSubclass(),
        type("_TrainingExecutionDecisionUnavailable", (RuntimeError,), {})(),
    ):
        monkeypatch.setattr(
            issuer.ProductionTrainingExecutionIssuerAdapter,
            "decide",
            lambda _self, _request, value=exception: (_ for _ in ()).throw(value),
        )
        with pytest.raises(TrainingError, match="TRAINING_EXECUTION_DECISION_INVALID"):
            issuer.issue_training_execution_approval(request)


def test_wrong_request_and_adapter_source_replacement_fail_closed(
    issuer_context,
) -> None:
    request = issuer_context.build()
    issuer._compose_production_training_execution_issuer()
    manual = TrainingExecutionRequest(**request.__dict__)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_REQUEST_INVALID"):
        issuer.issue_training_execution_approval(manual)

    registration = issuer._ADAPTER_REGISTRATION
    assert registration is not None
    object.__setattr__(
        registration.adapter,
        "_decision_source",
        issuer.TrainingExecutionDecisionSource(),
    )
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_ISSUER_UNAUTHORIZED"):
        issuer.issue_training_execution_approval(request)


def test_typed_decision_replay_is_independent(issuer_context, monkeypatch) -> None:
    request = issuer_context.build()
    issuer._compose_production_training_execution_issuer()
    decision = issuer.TrainingExecutionIssuerDecision(
        decision=issuer.TrainingExecutionIssuerDecisionValue.APPROVED,
        authorization_id="authorization-replay",
        issuer_id="issuer-1",
        approver_reference="approver-1",
        evidence_reference="evidence-1",
        request_fingerprint=request.request_fingerprint,
        issued_at="2026-08-12T12:00:00+09:00",
    )
    monkeypatch.setattr(
        issuer.ProductionTrainingExecutionIssuerAdapter,
        "decide",
        lambda _self, _request: decision,
    )
    issuer.issue_training_execution_approval(request)
    with pytest.raises(TrainingError, match="TRAINING_EXECUTION_DECISION_REPLAYED"):
        issuer.issue_training_execution_approval(request)


def test_returned_decision_request_mismatch_is_distinct(
    issuer_context, monkeypatch
) -> None:
    request = issuer_context.build()
    issuer._compose_production_training_execution_issuer()
    decision = issuer.TrainingExecutionIssuerDecision(
        decision=issuer.TrainingExecutionIssuerDecisionValue.APPROVED,
        authorization_id="authorization-mismatch",
        issuer_id="issuer-1",
        approver_reference="approver-1",
        evidence_reference="evidence-1",
        request_fingerprint="sha256:" + "9" * 64,
        issued_at="2026-08-12T12:00:00+09:00",
    )
    monkeypatch.setattr(
        issuer.ProductionTrainingExecutionIssuerAdapter,
        "decide",
        lambda _self, _request: decision,
    )
    with pytest.raises(
        TrainingError, match="TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH"
    ):
        issuer.issue_training_execution_approval(request)
    assert issuer._DECISION_PROVENANCE == {}
    assert issuer._DECISION_REPLAY_KEYS == set()


def test_submission_is_snapshotted_and_random_identity_is_not_generated(
    issuer_context,
) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    submission = _submission(request, authorization_id="business-action-id")
    _submit(capability, submission)
    object.__setattr__(submission, "authorization_id", "forged")
    approval = issuer.issue_training_execution_approval(request)
    assert approval.authorization_id == "business-action-id"
    assert "uuid" not in Path(issuer.__file__).read_text(encoding="utf-8").lower()


def test_backend_consumes_only_production_issued_approval(
    issuer_context, monkeypatch, tmp_path: Path
) -> None:
    request = issuer_context.build()
    request_snapshot = request.__dict__.copy()
    permission_snapshot = issuer_context.permission.__dict__.copy()
    capability = issuer._compose_production_training_execution_issuer()
    _submit(capability, _submission(request))
    calls = _prepare_backend_boundary(issuer_context, monkeypatch, tmp_path)
    approvals: list[TrainingExecutionApproval] = []
    original_consume = backend.consume_training_execution_approval

    def consume(approval, *args, **kwargs):
        approvals.append(approval)
        return original_consume(approval, *args, **kwargs)

    monkeypatch.setattr(backend, "consume_training_execution_approval", consume)

    with pytest.raises(TrainingError, match="SYNTHETIC_EXECUTION_BOUNDARY"):
        _run_backend(issuer_context, request)

    assert calls == ["backend"]
    assert request.__dict__ == request_snapshot
    assert issuer_context.permission.__dict__ == permission_snapshot
    assert len(approvals) == 1
    assert approval_boundary._APPROVAL_REGISTRY[id(approvals[0])].state == "consumed"


@pytest.mark.parametrize(
    ("case", "code"),
    (
        ("issuer_absent", "TRAINING_EXECUTION_ISSUER_UNAVAILABLE"),
        ("decision_absent", "TRAINING_EXECUTION_DECISION_UNAVAILABLE"),
        (
            "denied",
            "TRAINING_EXECUTION_APPROVAL_DENIED",
        ),
    ),
)
def test_backend_denied_and_unavailable_have_zero_downstream_calls(
    issuer_context, monkeypatch, tmp_path: Path, case: str, code: str
) -> None:
    request = issuer_context.build()
    if case != "issuer_absent":
        capability = issuer._compose_production_training_execution_issuer()
        if case == "denied":
            _submit(
                capability,
                _submission(
                    request,
                    decision=issuer.TrainingExecutionIssuerDecisionValue.DENIED,
                ),
            )
    calls = _prepare_backend_boundary(issuer_context, monkeypatch, tmp_path)
    approval_registry = dict(approval_boundary._APPROVAL_REGISTRY)

    with pytest.raises(TrainingError) as caught:
        _run_backend(issuer_context, request)

    assert caught.value.code == code
    assert calls == []
    assert approval_boundary._APPROVAL_REGISTRY == approval_registry


@pytest.mark.parametrize("result", (object(), SimpleNamespace(decision="approved")))
def test_backend_forged_decision_has_zero_downstream_calls(
    issuer_context, monkeypatch, tmp_path: Path, result: object
) -> None:
    request = issuer_context.build()
    issuer._compose_production_training_execution_issuer()
    calls = _prepare_backend_boundary(issuer_context, monkeypatch, tmp_path)
    approval_registry = dict(approval_boundary._APPROVAL_REGISTRY)
    monkeypatch.setattr(
        issuer.ProductionTrainingExecutionIssuerAdapter,
        "decide",
        lambda _self, _request: result,
    )

    with pytest.raises(TrainingError) as caught:
        _run_backend(issuer_context, request)

    assert caught.value.code == "TRAINING_EXECUTION_DECISION_INVALID"
    assert calls == []
    assert approval_boundary._APPROVAL_REGISTRY == approval_registry
    assert "object at" not in str(caught.value)


def test_backend_mismatched_decision_has_zero_downstream_calls(
    issuer_context, monkeypatch, tmp_path: Path
) -> None:
    request = issuer_context.build()
    issuer._compose_production_training_execution_issuer()
    calls = _prepare_backend_boundary(issuer_context, monkeypatch, tmp_path)
    approval_registry = dict(approval_boundary._APPROVAL_REGISTRY)
    mismatch = issuer.TrainingExecutionIssuerDecision(
        decision=issuer.TrainingExecutionIssuerDecisionValue.APPROVED,
        authorization_id="authorization-mismatch",
        issuer_id="issuer-1",
        approver_reference="approver-1",
        evidence_reference="evidence-1",
        request_fingerprint="sha256:" + "0" * 64,
        issued_at="2026-08-12T12:00:00+09:00",
    )
    monkeypatch.setattr(
        issuer.ProductionTrainingExecutionIssuerAdapter,
        "decide",
        lambda _self, _request: mismatch,
    )

    with pytest.raises(TrainingError) as caught:
        _run_backend(issuer_context, request)

    assert caught.value.code == "TRAINING_EXECUTION_APPROVAL_TARGET_MISMATCH"
    assert calls == []
    assert approval_boundary._APPROVAL_REGISTRY == approval_registry


def test_backend_replay_reaches_execution_boundary_exactly_once(
    issuer_context, monkeypatch, tmp_path: Path
) -> None:
    request = issuer_context.build()
    capability = issuer._compose_production_training_execution_issuer()
    _submit(capability, _submission(request, authorization_id="authorization-replay"))
    calls = _prepare_backend_boundary(issuer_context, monkeypatch, tmp_path)

    with pytest.raises(TrainingError, match="SYNTHETIC_EXECUTION_BOUNDARY"):
        _run_backend(issuer_context, request)
    with pytest.raises(TrainingError) as caught:
        _run_backend(issuer_context, request)

    assert caught.value.code == "TRAINING_EXECUTION_DECISION_REPLAYED"
    assert calls == ["backend"]


@pytest.mark.parametrize("mutation", ("identity", "fingerprint", "scope"))
def test_invalid_request_stops_before_decision_source_and_backend(
    issuer_context, monkeypatch, tmp_path: Path, mutation: str
) -> None:
    request = issuer_context.build()
    if mutation == "identity":
        request = TrainingExecutionRequest(**request.__dict__)
    elif mutation == "fingerprint":
        object.__setattr__(request, "request_fingerprint", "sha256:" + "0" * 64)
    else:
        object.__setattr__(request, "action", "evaluation")
    calls = _prepare_backend_boundary(issuer_context, monkeypatch, tmp_path)
    issuer_calls = 0

    def forbidden_issuer(_request):
        nonlocal issuer_calls
        issuer_calls += 1
        raise AssertionError("invalid request must not reach the decision source")

    monkeypatch.setattr(backend, "issue_training_execution_approval", forbidden_issuer)
    with pytest.raises(TrainingError) as caught:
        _run_backend(issuer_context, request)

    assert caught.value.code == "TRAINING_EXECUTION_REQUEST_INVALID"
    assert issuer_calls == 0
    assert calls == []


def test_backend_has_no_legacy_approval_injection_surface() -> None:
    parameters = inspect.signature(backend.run_full_pretraining).parameters
    assert "execution_approval" not in parameters
    assert "decision" not in parameters
    assert "decision_source" not in parameters
