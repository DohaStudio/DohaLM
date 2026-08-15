from __future__ import annotations

import secrets

import pytest

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
from test_postgres_c1_integration import C1Fixture, SCHEMA


pytest_plugins = ("test_postgres_c1_integration",)


@pytest.fixture(autouse=True)
def _isolated_process_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    import src.training.execution_issuer as issuer
    import src.training.production_full_pretraining_host as host_module

    monkeypatch.setattr(host_module, "_BOOTSTRAP_REGISTRATION", None)
    monkeypatch.setattr(issuer, "_ADAPTER_REGISTRATION", None)
    monkeypatch.setattr(issuer, "_SUBMISSION_BINDINGS", {})
    monkeypatch.setattr(issuer, "_DECISION_PROVENANCE", {})
    monkeypatch.setattr(issuer, "_DECISION_REPLAY_KEYS", set())


@pytest.mark.integration
def test_c3_composition_preflights_and_wires_existing_host_without_mutation(
    c1_postgres: C1Fixture,
) -> None:
    from psycopg import sql

    resolver_password = secrets.token_urlsafe(32)
    journal_password = secrets.token_urlsafe(32)
    with c1_postgres.factory.connection() as owner:
        owner.execute(
            sql.SQL("ALTER ROLE dohalm_training_resolver PASSWORD {}").format(
                sql.Literal(resolver_password)
            )
        )
        owner.execute(
            sql.SQL("ALTER ROLE dohalm_training_journal PASSWORD {}").format(
                sql.Literal(journal_password)
            )
        )
        before = owner.execute(
            f"SELECT (SELECT count(*) FROM {SCHEMA}.training_execution_journal), "
            f"(SELECT count(*) FROM {SCHEMA}.training_execution_phase_event)"
        ).fetchone()
        owner.commit()
    root = None
    try:
        configuration = _PostgresTrainingCompositionConfiguration(
            provider="postgresql",
            environment="isolated_test",
            host=c1_postgres.settings.host,
            port=c1_postgres.settings.port,
            database=c1_postgres.settings.database,
            resolver_password=resolver_password,
            journal_password=journal_password,
            application_name="dohalm-c3-integration",
            process_boundary_id="process:c3-integration",
            decision_authority_id="55555555-5555-4555-8555-555555555555",
            prerequisite_policy_reference="prerequisite-policy:c3-integration",
            decision_policy_reference="decision-policy:c3-integration",
            activation_authority_reference="activation:c3-synthetic",
            activation_evidence_reference="evidence:c3-synthetic-only",
            connect_timeout_seconds=5,
            statement_timeout_ms=15_000,
            transaction_timeout_ms=30_000,
            sslmode="disable",
            sslrootcert=None,
        )
        root = _compose_postgres_training_host(configuration)
        result = root.preflight()
        assert result.resolver_connectivity is True
        assert result.journal_connectivity is True
        assert result.role_separation is True
        assert result.mutation_count == 0

        host = root.startup(
            _ProductionTrainingActivationDecision(
                authorized=True,
                provider="postgresql",
                authority_reference="activation:c3-synthetic",
                evidence_reference="evidence:c3-synthetic-only",
                process_boundary_id="process:c3-integration",
            )
        )
        assert type(host) is ProductionFullPretrainingHost
        assert (
            type(host._prerequisite_resolver) is _PostgresTrainingPrerequisiteResolver
        )
        assert type(host._decision_resolver) is _PostgresTrainingDecisionResolver
        assert type(host._journal) is _PostgresTrainingExecutionJournal
        assert host._prerequisite_resolver is root._prerequisite_resolver
        assert host._decision_resolver is root._decision_resolver
        assert host._journal is root._journal
        assert host._process_boundary_id == "process:c3-integration"

        for factory, isolation in (
            (root._resolver_factory, "REPEATABLE READ"),
            (root._journal_factory, "READ COMMITTED"),
        ):
            with pytest.raises(Exception) as denied:
                with factory.transaction(isolation=isolation, read_only=True) as conn:
                    conn.execute(
                        f"SELECT count(*) FROM {SCHEMA}.training_execution_journal"
                    )
            assert denied.value.sqlstate == "42501"

        with c1_postgres.factory.connection() as owner:
            after = owner.execute(
                f"SELECT (SELECT count(*) FROM {SCHEMA}.training_execution_journal), "
                f"(SELECT count(*) FROM {SCHEMA}.training_execution_phase_event)"
            ).fetchone()
        assert after == before
    finally:
        if root is not None:
            resolver_factory = root._resolver_factory
            journal_factory = root._journal_factory
            root.shutdown()
            root.shutdown()
            assert resolver_factory._delegate is None
            assert journal_factory._delegate is None
            assert root._configuration is None
            assert root._host is None
            import src.training.execution_issuer as issuer
            import src.training.production_full_pretraining_host as host_module

            assert host_module._BOOTSTRAP_REGISTRATION is None
            assert issuer._ADAPTER_REGISTRATION is None
        with c1_postgres.factory.connection() as owner:
            owner.execute("ALTER ROLE dohalm_training_resolver PASSWORD NULL")
            owner.execute("ALTER ROLE dohalm_training_journal PASSWORD NULL")
            owner.commit()
