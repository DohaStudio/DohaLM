from __future__ import annotations

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


DECISION_ID = "55555555-5555-4555-8555-555555555555"


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
    calls: list[tuple[object, ...]] = []

    with pytest.raises(
        TrainingError, match="TRAINING_COMPOSITION_ACTIVATION_NOT_AUTHORIZED"
    ):
        root.startup(_activation())

    root._preflight_complete = True
    with pytest.raises(
        TrainingError, match="TRAINING_COMPOSITION_ACTIVATION_NOT_AUTHORIZED"
    ):
        root.startup(_activation(authorized=False))

    host = object()

    def bootstrap(*args: object, **kwargs: object) -> object:
        calls.append((*args, kwargs))
        return host

    monkeypatch.setattr(
        composition, "_bootstrap_production_full_pretraining_host", bootstrap
    )
    assert root.startup(_activation()) is host
    assert root.startup(_activation()) is host
    assert len(calls) == 1
    assert calls[0][0] is root._prerequisite_resolver
    assert calls[0][1] is root._decision_resolver
    assert calls[0][2] is root._journal
    assert calls[0][3]["process_boundary_id"] == "process:c3-contract"
    assert calls[0][3]["decision_authority_id"] == DECISION_ID
    root.shutdown()


def test_c3_preflight_error_mapping_is_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    secret = "synthetic-resolver-only"
    root = _compose_postgres_training_host(_configuration(resolver_password=secret))

    def denied(_request: object) -> None:
        raise TrainingError("TRAINING_DATABASE_PERMISSION_DENIED", secret)

    monkeypatch.setattr(root._prerequisite_resolver, "resolve", denied)
    try:
        with pytest.raises(
            TrainingError, match="TRAINING_COMPOSITION_PERMISSION_DENIED"
        ) as captured:
            root.preflight()
        assert secret not in str(captured.value)
        assert "127.0.0.1" not in str(captured.value)
    finally:
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
    with pytest.raises(TrainingError, match="TRAINING_COMPOSITION_SHUTDOWN"):
        root.preflight()
