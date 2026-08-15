from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.training.errors import TrainingError
from src.training import production_composition as composition
from src.training.postgres_training_adapters import (
    _PostgresTrainingDecisionResolver,
    _PostgresTrainingExecutionJournal,
    _PostgresTrainingPrerequisiteResolver,
)
from src.training.production_composition import (
    _PostgresTrainingCompositionConfiguration,
    _ProductionTrainingActivationDecision,
    _compose_postgres_training_host,
)
from src.training.production_full_pretraining_host import ProductionFullPretrainingHost


DECISION_ID = "55555555-5555-4555-8555-555555555555"


@pytest.fixture(autouse=True)
def _isolated_process_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.training.execution_issuer as issuer
    import src.training.production_full_pretraining_host as host_module

    monkeypatch.setattr(host_module, "_BOOTSTRAP_REGISTRATION", None)
    monkeypatch.setattr(issuer, "_ADAPTER_REGISTRATION", None)
    monkeypatch.setattr(issuer, "_SUBMISSION_BINDINGS", {})
    monkeypatch.setattr(issuer, "_DECISION_PROVENANCE", {})
    monkeypatch.setattr(issuer, "_DECISION_REPLAY_KEYS", set())


def _configuration(**changes: object) -> _PostgresTrainingCompositionConfiguration:
    values: dict[str, object] = {
        "provider": "postgresql",
        "environment": "isolated_test",
        "host": "127.0.0.1",
        "port": 5432,
        "database": "dohalm_c3_contract",
        "resolver_password": "synthetic-resolver-only",
        "journal_password": "synthetic-journal-only",
        "application_name": "dohalm-c3-contract",
        "process_boundary_id": "process:c3-contract",
        "decision_authority_id": DECISION_ID,
        "prerequisite_policy_reference": "prerequisite-policy:c3",
        "decision_policy_reference": "decision-policy:c3",
        "activation_authority_reference": "activation:c3-contract",
        "activation_evidence_reference": "evidence:c3-contract",
        "connect_timeout_seconds": 5,
        "statement_timeout_ms": 15_000,
        "transaction_timeout_ms": 30_000,
        "sslmode": "disable",
        "sslrootcert": None,
    }
    values.update(changes)
    return _PostgresTrainingCompositionConfiguration(**values)


def _activation(**changes: object) -> _ProductionTrainingActivationDecision:
    values: dict[str, object] = {
        "authorized": True,
        "provider": "postgresql",
        "authority_reference": "activation:c3-contract",
        "evidence_reference": "evidence:c3-contract",
        "process_boundary_id": "process:c3-contract",
    }
    values.update(changes)
    return _ProductionTrainingActivationDecision(**values)


def _complete_preflight(root: object, monkeypatch: pytest.MonkeyPatch) -> object:
    monkeypatch.setattr(
        root._prerequisite_resolver,
        "resolve",
        lambda _request: (_ for _ in ()).throw(
            TrainingError("TRAINING_HOST_PREREQUISITE_UNAVAILABLE", "missing")
        ),
    )
    monkeypatch.setattr(
        root._decision_resolver,
        "resolve",
        lambda _request: (_ for _ in ()).throw(
            TrainingError("TRAINING_EXECUTION_DECISION_UNAVAILABLE", "missing")
        ),
    )
    monkeypatch.setattr(root._journal, "read", lambda _run_id: None)
    return root.preflight()


def test_c3_import_and_default_provider_are_non_activating() -> None:
    import src.training.execution_issuer as issuer
    import src.training.production_full_pretraining_host as host_module

    assert host_module._BOOTSTRAP_REGISTRATION is None
    assert issuer._ADAPTER_REGISTRATION is None
    __import__("src.training.production_composition")
    assert host_module._BOOTSTRAP_REGISTRATION is None
    assert issuer._ADAPTER_REGISTRATION is None
    disabled = _PostgresTrainingCompositionConfiguration()
    assert "disabled" not in repr(disabled)
    with pytest.raises(TrainingError, match="TRAINING_COMPOSITION_PROVIDER_DISABLED"):
        _compose_postgres_training_host(disabled)


def test_c3_complete_configuration_constructs_exact_role_scoped_graph() -> None:
    root = _compose_postgres_training_host(_configuration())
    try:
        assert (
            type(root._prerequisite_resolver) is _PostgresTrainingPrerequisiteResolver
        )
        assert type(root._decision_resolver) is _PostgresTrainingDecisionResolver
        assert type(root._journal) is _PostgresTrainingExecutionJournal
        assert root._resolver_factory is not root._journal_factory
        assert root._resolver_factory.role == "dohalm_training_resolver"
        assert root._journal_factory.role == "dohalm_training_journal"
        assert root._host is None
    finally:
        root.shutdown()


def test_c3_construction_has_no_connection_or_host_registration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.training.execution_issuer as issuer
    import src.training.production_full_pretraining_host as host_module

    monkeypatch.setattr(
        "psycopg.connect",
        lambda **_: (_ for _ in ()).throw(AssertionError("unexpected DB connect")),
    )
    root = _compose_postgres_training_host(_configuration())
    assert host_module._BOOTSTRAP_REGISTRATION is None
    assert issuer._ADAPTER_REGISTRATION is None
    root.shutdown()


@pytest.mark.parametrize(
    "change",
    [
        {"resolver_password": "same", "journal_password": "same"},
        {"host": "0.0.0.0"},
        {"statement_timeout_ms": 40_000, "transaction_timeout_ms": 30_000},
        {"sslmode": "verify-full"},
        {"activation_authority_reference": None},
        {"activation_evidence_reference": None},
    ],
)
def test_c3_configuration_fails_closed(change: dict[str, object]) -> None:
    with pytest.raises(
        TrainingError, match="TRAINING_COMPOSITION_CONFIGURATION_INVALID"
    ):
        _configuration(**change)


def test_c3_production_tls_requires_absolute_existing_non_symlink_ca(
    tmp_path: Path,
) -> None:
    ca = tmp_path / "root.crt"
    ca.write_text("synthetic CA only", encoding="utf-8")
    config = _configuration(
        environment="production",
        host="db.internal.invalid",
        sslmode="verify-full",
        sslrootcert=ca.resolve(),
    )
    assert "root.crt" not in repr(config)
    with pytest.raises(
        TrainingError, match="TRAINING_COMPOSITION_CONFIGURATION_INVALID"
    ):
        _configuration(
            environment="production",
            host="db.internal.invalid",
            sslmode="verify-full",
            sslrootcert=Path("relative.crt"),
        )


def test_c3_non_mutating_preflight_uses_all_three_restricted_adapters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _compose_postgres_training_host(_configuration())
    calls: list[str] = []

    def prerequisite(_request: object) -> None:
        calls.append("prerequisite")
        raise TrainingError(
            "TRAINING_HOST_PREREQUISITE_UNAVAILABLE", "synthetic missing"
        )

    def decision(_request: object) -> None:
        calls.append("decision")
        raise TrainingError("TRAINING_EXECUTION_DECISION_UNAVAILABLE", "missing")

    def journal(_run_id: str) -> None:
        calls.append("journal-read")
        return None

    monkeypatch.setattr(root._prerequisite_resolver, "resolve", prerequisite)
    monkeypatch.setattr(root._decision_resolver, "resolve", decision)
    monkeypatch.setattr(root._journal, "read", journal)
    try:
        result = root.preflight()
        assert calls == ["prerequisite", "decision", "journal-read"]
        assert result.configuration_valid is True
        assert result.resolver_connectivity is True
        assert result.journal_connectivity is True
        assert result.role_separation is True
        assert result.mutation_count == 0
        assert root.preflight() is not result
        assert calls == ["prerequisite", "decision", "journal-read"]
    finally:
        root.shutdown()


def test_c3_activation_guard_precedes_existing_host_bootstrap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _compose_postgres_training_host(_configuration())

    with pytest.raises(
        TrainingError, match="TRAINING_COMPOSITION_ACTIVATION_NOT_AUTHORIZED"
    ):
        root.startup(_activation())
    _complete_preflight(root, monkeypatch)

    with pytest.raises(
        TrainingError, match="TRAINING_COMPOSITION_ACTIVATION_NOT_AUTHORIZED"
    ):
        root.startup(_activation(authorized=False))
    assert root.lifecycle_state is composition._PostgresTrainingLifecycleState.SHUTDOWN

    root = _compose_postgres_training_host(_configuration())
    _complete_preflight(root, monkeypatch)
    calls: list[tuple[object, ...]] = []
    host = object()

    def bootstrap(*args: object, **kwargs: object) -> object:
        calls.append((*args, kwargs))
        return host

    monkeypatch.setattr(
        composition, "_bootstrap_production_full_pretraining_host", bootstrap
    )
    assert root.startup(_activation()) is host
    assert len(calls) == 1
    assert calls[0][0] is root._prerequisite_resolver
    assert calls[0][1] is root._decision_resolver
    assert calls[0][2] is root._journal
    assert calls[0][3]["process_boundary_id"] == "process:c3-contract"
    assert calls[0][3]["decision_authority_id"] == DECISION_ID
    assert calls[0][3]["lifecycle_lease"] is root._lease
    with pytest.raises(
        TrainingError, match="TRAINING_COMPOSITION_ACTIVATION_NOT_AUTHORIZED"
    ):
        root.startup(_activation())
    root.shutdown()


def test_c3_preflight_error_mapping_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "synthetic-resolver-only"
    root = _compose_postgres_training_host(_configuration(resolver_password=secret))

    def denied(_request: object) -> None:
        raise TrainingError("TRAINING_DATABASE_PERMISSION_DENIED", secret)

    monkeypatch.setattr(root._prerequisite_resolver, "resolve", denied)
    resolver_factory = root._resolver_factory
    journal_factory = root._journal_factory
    with pytest.raises(
        TrainingError, match="TRAINING_COMPOSITION_PERMISSION_DENIED"
    ) as captured:
        root.preflight()
    assert secret not in str(captured.value)
    assert "127.0.0.1" not in str(captured.value)
    assert root.lifecycle_state is composition._PostgresTrainingLifecycleState.SHUTDOWN
    assert resolver_factory._delegate is None
    assert journal_factory._delegate is None
    root.shutdown()


def test_c3_partial_construction_closes_owned_prerequisite(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owned = SimpleNamespace(closed=False)
    owned.close = lambda: setattr(owned, "closed", True)
    monkeypatch.setattr(
        composition, "_PostgresTrainingPrerequisiteResolver", lambda *_a, **_k: owned
    )
    monkeypatch.setattr(
        composition,
        "_PostgresTrainingDecisionResolver",
        lambda *_a, **_k: (_ for _ in ()).throw(RuntimeError("synthetic")),
    )
    with pytest.raises(TrainingError, match="TRAINING_COMPOSITION_CONSTRUCTION_FAILED"):
        _compose_postgres_training_host(_configuration())
    assert owned.closed is True


@pytest.mark.parametrize(
    "stage",
    [
        "resolver_factory",
        "journal_factory",
        "prerequisite_adapter",
        "decision_adapter",
        "journal_adapter",
    ],
)
def test_c3_construction_failure_matrix_revokes_every_created_factory(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    original_factory = composition._PostgresTrainingConnectionFactory
    original_wrapper = composition._RevocablePostgresTrainingConnectionFactory
    original_prerequisite = composition._PostgresTrainingPrerequisiteResolver
    original_decision = composition._PostgresTrainingDecisionResolver
    original_journal = composition._PostgresTrainingExecutionJournal
    raw_calls = 0
    wrappers: list[object] = []
    prerequisites: list[object] = []

    def factory(settings: object) -> object:
        nonlocal raw_calls
        raw_calls += 1
        if stage == "resolver_factory" and raw_calls == 1:
            raise RuntimeError("synthetic resolver factory failure")
        if stage == "journal_factory" and raw_calls == 2:
            raise RuntimeError("synthetic journal factory failure")
        return original_factory(settings)

    def wrapper(delegate: object, lease: object) -> object:
        value = original_wrapper(delegate, lease)
        wrappers.append(value)
        return value

    def prerequisite(*args: object, **kwargs: object) -> object:
        if stage == "prerequisite_adapter":
            raise RuntimeError("synthetic prerequisite failure")
        value = original_prerequisite(*args, **kwargs)
        prerequisites.append(value)
        return value

    def decision(*args: object, **kwargs: object) -> object:
        if stage == "decision_adapter":
            raise RuntimeError("synthetic decision failure")
        return original_decision(*args, **kwargs)

    def journal(*args: object, **kwargs: object) -> object:
        if stage == "journal_adapter":
            raise RuntimeError("synthetic journal failure")
        return original_journal(*args, **kwargs)

    monkeypatch.setattr(composition, "_PostgresTrainingConnectionFactory", factory)
    monkeypatch.setattr(
        composition, "_RevocablePostgresTrainingConnectionFactory", wrapper
    )
    monkeypatch.setattr(
        composition, "_PostgresTrainingPrerequisiteResolver", prerequisite
    )
    monkeypatch.setattr(composition, "_PostgresTrainingDecisionResolver", decision)
    monkeypatch.setattr(composition, "_PostgresTrainingExecutionJournal", journal)

    with pytest.raises(TrainingError, match="TRAINING_COMPOSITION_CONSTRUCTION_FAILED"):
        _compose_postgres_training_host(_configuration())
    assert all(value._delegate is None for value in wrappers)
    assert all(value._closed is True for value in prerequisites)


def test_c3_shutdown_is_idempotent_and_blocks_future_preflight(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _compose_postgres_training_host(_configuration())
    closes = 0

    def close() -> None:
        nonlocal closes
        closes += 1

    monkeypatch.setattr(root._prerequisite_resolver, "close", close)
    root.shutdown()
    root.shutdown()
    assert closes == 1
    assert root.lifecycle_state is composition._PostgresTrainingLifecycleState.SHUTDOWN
    assert root._configuration is None
    assert root._resolver_factory is None
    assert root._journal_factory is None
    assert root._prerequisite_resolver is None
    assert root._decision_resolver is None
    assert root._journal is None
    assert root._host is None
    with pytest.raises(TrainingError, match="TRAINING_COMPOSITION_LIFECYCLE_REVOKED"):
        root.preflight()


def test_c3_shutdown_revokes_retained_host_and_credential_factories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.training.execution_issuer as issuer
    import src.training.production_full_pretraining_host as host_module

    root = _compose_postgres_training_host(_configuration())
    _complete_preflight(root, monkeypatch)
    resolver_factory = root._resolver_factory
    journal_factory = root._journal_factory
    calls = {"prerequisite": 0, "decision": 0, "journal": 0}

    monkeypatch.setattr(
        root._prerequisite_resolver,
        "resolve",
        lambda _request: calls.__setitem__("prerequisite", calls["prerequisite"] + 1),
    )
    monkeypatch.setattr(
        root._decision_resolver,
        "resolve",
        lambda _request: calls.__setitem__("decision", calls["decision"] + 1),
    )
    monkeypatch.setattr(
        root._journal,
        "read",
        lambda _run_id: calls.__setitem__("journal", calls["journal"] + 1),
    )
    host = root.startup(_activation())
    assert host_module._BOOTSTRAP_REGISTRATION.host is host
    assert issuer._ADAPTER_REGISTRATION is not None

    root.shutdown()

    with pytest.raises(TrainingError, match="TRAINING_COMPOSITION_LIFECYCLE_REVOKED"):
        host.run(object())
    with pytest.raises(TrainingError, match="TRAINING_COMPOSITION_LIFECYCLE_REVOKED"):
        with resolver_factory.transaction(isolation="REPEATABLE READ", read_only=True):
            pass
    assert resolver_factory._delegate is None
    assert journal_factory._delegate is None
    assert calls == {"prerequisite": 0, "decision": 0, "journal": 0}
    assert host_module._BOOTSTRAP_REGISTRATION is None
    assert issuer._ADAPTER_REGISTRATION is None
    assert issuer._SUBMISSION_BINDINGS == {}


def test_c3_stale_shutdown_cannot_clear_new_registration_or_reuse_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.training.production_full_pretraining_host as host_module

    first = _compose_postgres_training_host(_configuration())
    _complete_preflight(first, monkeypatch)
    first_factory = first._resolver_factory
    first_host = first.startup(_activation())
    first.shutdown()

    second = _compose_postgres_training_host(
        _configuration(
            resolver_password="synthetic-resolver-b",
            journal_password="synthetic-journal-b",
            application_name="dohalm-c3-contract-b",
            process_boundary_id="process:c3-contract-b",
            activation_evidence_reference="evidence:c3-contract-b",
        )
    )
    _complete_preflight(second, monkeypatch)
    second_host = second.startup(
        _activation(
            evidence_reference="evidence:c3-contract-b",
            process_boundary_id="process:c3-contract-b",
        )
    )
    assert second_host is not first_host
    assert first_factory._delegate is None
    with pytest.raises(TrainingError, match="TRAINING_COMPOSITION_LIFECYCLE_REVOKED"):
        first_host.run(object())
    with pytest.raises(TrainingError, match="TRAINING_HOST_INTENT_INVALID"):
        second_host.run(object())

    assert host_module._release_production_full_pretraining_host(first_host) is False
    first.shutdown()
    assert host_module._BOOTSTRAP_REGISTRATION.host is second_host
    second.shutdown()
    assert host_module._BOOTSTRAP_REGISTRATION is None


def test_c3_startup_failure_revokes_and_clears_complete_graph(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import src.training.execution_issuer as issuer
    import src.training.production_full_pretraining_host as host_module

    root = _compose_postgres_training_host(_configuration())
    _complete_preflight(root, monkeypatch)
    resolver_factory = root._resolver_factory
    journal_factory = root._journal_factory
    monkeypatch.setattr(
        composition,
        "_bootstrap_production_full_pretraining_host",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            TrainingError("TRAINING_HOST_BOOTSTRAP_FAILED", "synthetic")
        ),
    )

    with pytest.raises(TrainingError, match="TRAINING_HOST_BOOTSTRAP_FAILED"):
        root.startup(_activation())
    assert root.lifecycle_state is composition._PostgresTrainingLifecycleState.SHUTDOWN
    assert resolver_factory._delegate is None
    assert journal_factory._delegate is None
    assert root._configuration is None
    assert root._host is None
    assert host_module._BOOTSTRAP_REGISTRATION is None
    assert issuer._ADAPTER_REGISTRATION is None
    root.shutdown()


def test_c3_cleanup_error_never_overwrites_original_preflight_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _compose_postgres_training_host(_configuration())
    original_close = root._prerequisite_resolver.close

    def close_then_fail() -> None:
        original_close()
        raise RuntimeError("synthetic-private-cleanup-path")

    monkeypatch.setattr(root._prerequisite_resolver, "close", close_then_fail)
    monkeypatch.setattr(
        root._prerequisite_resolver,
        "resolve",
        lambda _request: (_ for _ in ()).throw(
            TrainingError("TRAINING_DATABASE_PERMISSION_DENIED", "raw-secret")
        ),
    )
    with pytest.raises(
        TrainingError, match="TRAINING_COMPOSITION_PERMISSION_DENIED"
    ) as captured:
        root.preflight()
    assert "cleanup" not in str(captured.value)
    assert "secret" not in str(captured.value)
    assert root.lifecycle_state is composition._PostgresTrainingLifecycleState.SHUTDOWN


def test_c3_shutdown_drains_started_host_and_rejects_new_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _compose_postgres_training_host(_configuration())
    _complete_preflight(root, monkeypatch)
    host = root.startup(_activation())
    entered = threading.Event()
    release = threading.Event()
    shutdown_done = threading.Event()

    def blocked_run(_host: object, _intent: object) -> str:
        entered.set()
        assert release.wait(timeout=5)
        return "completed-before-revoke"

    monkeypatch.setattr(ProductionFullPretrainingHost, "_run", blocked_run)

    def shutdown() -> None:
        root.shutdown()
        shutdown_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        running = executor.submit(host.run, object())
        assert entered.wait(timeout=5)
        stopping = executor.submit(shutdown)
        assert not shutdown_done.wait(timeout=0.1)
        with pytest.raises(
            TrainingError, match="TRAINING_COMPOSITION_LIFECYCLE_REVOKED"
        ):
            host.run(object())
        release.set()
        assert running.result(timeout=5) == "completed-before-revoke"
        stopping.result(timeout=5)
    assert shutdown_done.is_set()
    with pytest.raises(TrainingError, match="TRAINING_COMPOSITION_LIFECYCLE_REVOKED"):
        host.run(object())


def test_c3_shutdown_and_preflight_race_drains_without_reactivation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    root = _compose_postgres_training_host(_configuration())
    entered = threading.Event()
    release = threading.Event()
    shutdown_done = threading.Event()

    def prerequisite(_request: object) -> None:
        entered.set()
        assert release.wait(timeout=5)
        raise TrainingError("TRAINING_HOST_PREREQUISITE_UNAVAILABLE", "missing")

    monkeypatch.setattr(root._prerequisite_resolver, "resolve", prerequisite)
    monkeypatch.setattr(
        root._decision_resolver,
        "resolve",
        lambda _request: (_ for _ in ()).throw(
            TrainingError("TRAINING_EXECUTION_DECISION_UNAVAILABLE", "missing")
        ),
    )
    monkeypatch.setattr(root._journal, "read", lambda _run_id: None)

    def shutdown() -> None:
        root.shutdown()
        shutdown_done.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        preflight = executor.submit(root.preflight)
        assert entered.wait(timeout=5)
        stopping = executor.submit(shutdown)
        assert not shutdown_done.wait(timeout=0.1)
        release.set()
        assert preflight.result(timeout=5).mutation_count == 0
        stopping.result(timeout=5)
    assert root.lifecycle_state is composition._PostgresTrainingLifecycleState.SHUTDOWN


def test_c3_duplicate_shutdown_is_idempotent_under_concurrency() -> None:
    root = _compose_postgres_training_host(_configuration())
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = tuple(executor.map(lambda _: root.shutdown(), range(2)))
    assert results == (None, None)
    assert root.lifecycle_state is composition._PostgresTrainingLifecycleState.SHUTDOWN
