from __future__ import annotations

import secrets
import uuid
from dataclasses import replace

import pytest

from src.training.errors import TrainingError
from src.training.postgres_training_adapters import (
    _PostgresTrainingConnectionFactory,
    _PostgresTrainingConnectionSettings,
    _PostgresTrainingDecisionResolver,
    _PostgresTrainingExecutionJournal,
    _PostgresTrainingPrerequisiteResolver,
)
from src.training.production_host_foundation import (
    ProductionTrainingHostIntent,
    TrainingDecisionResolutionRequest,
    TrainingOrchestrationClaimRequest,
    TrainingOrchestrationIdentity,
    TrainingOrchestrationPhase,
    TrainingOrchestrationTransition,
)
from src.training.production_orchestration_seams import (
    TrainingPrerequisiteResolutionRequest,
)
from test_postgres_c1_integration import C1Fixture, SCHEMA

pytest_plugins = ("test_postgres_c1_integration",)


@pytest.mark.integration
def test_c2_journal_adapter_uses_login_role_short_transactions_and_restricted_functions(
    c1_postgres: C1Fixture,
) -> None:
    from psycopg import sql

    password = secrets.token_urlsafe(32)
    with c1_postgres.factory.connection() as owner:
        owner.execute(
            sql.SQL("ALTER ROLE dohalm_training_journal PASSWORD {}").format(
                sql.Literal(password)
            )
        )
        owner.commit()
    try:
        settings = _PostgresTrainingConnectionSettings(
            environment="isolated_test",
            host=c1_postgres.settings.host,
            port=c1_postgres.settings.port,
            database=c1_postgres.settings.database,
            user="dohalm_training_journal",
            password=password,
            role="dohalm_training_journal",
            application_name="dohalm-c2-journal-contract",
            sslmode="disable",
        )
        factory = _PostgresTrainingConnectionFactory(settings)
        journal = _PostgresTrainingExecutionJournal(factory)
        suffix = uuid.uuid4().hex
        identity = TrainingOrchestrationIdentity(
            run_id=f"run:c2-adapter-{suffix}",
            request_fingerprint="sha256:" + "1" * 64,
        )
        request = TrainingOrchestrationClaimRequest(
            identity=identity,
            intent_fingerprint="sha256:" + "2" * 64,
            orchestration_correlation_id=f"correlation:c2-{suffix}",
            dataset_version_id="dataset-version:c2-adapter",
            dataset_manifest_id="dataset-manifest:c2-adapter",
            dataset_pair_fingerprint="sha256:" + "3" * 64,
            config_fingerprint="sha256:" + "4" * 64,
            readiness_fingerprint="sha256:" + "5" * 64,
            source_commit="a" * 40,
            prerequisite_policy_reference="prerequisite-policy:c2-adapter",
            process_boundary_id="process:c2-adapter",
        )
        claimed = journal.claim(request)
        assert claimed.status.value == "acquired"
        assert claimed.record.claim == request
        assert journal.read(identity.run_id) == claimed.record
        transitioned = journal.transition(
            TrainingOrchestrationTransition(
                identity=identity,
                process_boundary_id=request.process_boundary_id,
                expected_phase=TrainingOrchestrationPhase.CLAIMED,
                expected_version=1,
                next_phase=TrainingOrchestrationPhase.RESOLVED,
            )
        )
        assert transitioned.phase is TrainingOrchestrationPhase.RESOLVED
        assert transitioned.journal_version == 2
        assert journal.read(identity.run_id) == transitioned
        with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
            journal.claim(request)
        with pytest.raises(TrainingError, match="TRAINING_HOST_JOURNAL_CONFLICT"):
            journal.transition(
                TrainingOrchestrationTransition(
                    identity=identity,
                    process_boundary_id=request.process_boundary_id,
                    expected_phase=TrainingOrchestrationPhase.CLAIMED,
                    expected_version=1,
                    next_phase=TrainingOrchestrationPhase.RESOLVED,
                )
            )
        terminal = journal.transition(
            TrainingOrchestrationTransition(
                identity=identity,
                process_boundary_id=request.process_boundary_id,
                expected_phase=TrainingOrchestrationPhase.RESOLVED,
                expected_version=2,
                next_phase=TrainingOrchestrationPhase.FAILED,
                reason_code="SYNTHETIC_FAILURE",
            )
        )
        assert terminal.phase is TrainingOrchestrationPhase.FAILED
        replay = journal.claim(request)
        assert replay.status.value == "replay"
        assert replay.record == terminal

        manual_identity = TrainingOrchestrationIdentity(
            run_id=f"run:c2-manual-{suffix}",
            request_fingerprint="sha256:" + "6" * 64,
        )
        manual_request = replace(
            request,
            identity=manual_identity,
            orchestration_correlation_id=f"correlation:c2-manual-{suffix}",
        )
        manual_claim = journal.claim(manual_request)
        manual = journal.transition(
            TrainingOrchestrationTransition(
                identity=manual_identity,
                process_boundary_id=manual_request.process_boundary_id,
                expected_phase=manual_claim.record.phase,
                expected_version=manual_claim.record.journal_version,
                next_phase=TrainingOrchestrationPhase.MANUAL_RECONCILIATION_REQUIRED,
                reason_code="AMBIGUOUS_COMMIT",
            )
        )
        assert manual.reconciliation_required is True
        assert manual.reason_code == "AMBIGUOUS_COMMIT"
        with pytest.raises(Exception) as denied:
            with factory.transaction(
                isolation="READ COMMITTED", read_only=True
            ) as restricted:
                restricted.execute(
                    f"SELECT count(*) FROM {SCHEMA}.training_execution_journal"
                )
        assert denied.value.sqlstate == "42501"
    finally:
        with c1_postgres.factory.connection() as owner:
            owner.execute("ALTER ROLE dohalm_training_journal PASSWORD NULL")
            owner.commit()


@pytest.mark.integration
def test_c2_resolvers_use_login_role_read_only_snapshots_and_fail_closed_missing(
    c1_postgres: C1Fixture,
) -> None:
    from psycopg import sql

    password = secrets.token_urlsafe(32)
    with c1_postgres.factory.connection() as owner:
        owner.execute(
            sql.SQL("ALTER ROLE dohalm_training_resolver PASSWORD {}").format(
                sql.Literal(password)
            )
        )
        owner.commit()
    prerequisite = None
    try:
        factory = _PostgresTrainingConnectionFactory(
            _PostgresTrainingConnectionSettings(
                environment="isolated_test",
                host=c1_postgres.settings.host,
                port=c1_postgres.settings.port,
                database=c1_postgres.settings.database,
                user="dohalm_training_resolver",
                password=password,
                role="dohalm_training_resolver",
                application_name="dohalm-c2-resolver-contract",
                sslmode="disable",
            )
        )
        intent = ProductionTrainingHostIntent(
            action="full_pretraining",
            execution_mode="fresh",
            dataset_version_reference="dataset-version:11111111-1111-4111-8111-111111111111",
            dataset_manifest_reference="dataset-manifest:22222222-2222-4222-8222-222222222222",
            expected_dataset_pair_fingerprint="sha256:" + "3" * 64,
            training_config_reference="config:33333333-3333-4333-8333-333333333333",
            expected_config_fingerprint="sha256:" + "4" * 64,
            readiness_evidence_reference="readiness:44444444-4444-4444-8444-444444444444",
            expected_readiness_fingerprint="sha256:" + "5" * 64,
            run_id="run:c2-resolver-missing",
            output_logical_root="experiments/full-pretraining-candidate-a",
            decision_evidence_reference="decision:55555555-5555-4555-8555-555555555555",
        )
        prerequisite = _PostgresTrainingPrerequisiteResolver(
            factory, policy_reference="prerequisite-policy:c2-contract"
        )
        with pytest.raises(
            TrainingError, match="TRAINING_HOST_PREREQUISITE_UNAVAILABLE"
        ):
            prerequisite.resolve(
                TrainingPrerequisiteResolutionRequest(
                    intent=intent,
                    intent_fingerprint="sha256:" + "6" * 64,
                    dataset_version_authority_id="11111111-1111-4111-8111-111111111111",
                    dataset_manifest_authority_id="22222222-2222-4222-8222-222222222222",
                    config_authority_id="33333333-3333-4333-8333-333333333333",
                    readiness_authority_id="44444444-4444-4444-8444-444444444444",
                )
            )
        with pytest.raises(
            TrainingError, match="TRAINING_EXECUTION_DECISION_UNAVAILABLE"
        ):
            _PostgresTrainingDecisionResolver(
                factory, policy_reference="decision-policy:c2-contract"
            ).resolve(
                TrainingDecisionResolutionRequest(
                    intent=intent,
                    decision_authority_id="55555555-5555-4555-8555-555555555555",
                    request_fingerprint="sha256:" + "7" * 64,
                    dataset_version_id="dataset-version:c2",
                    dataset_manifest_id="dataset-manifest:c2",
                    dataset_pair_authority_id="66666666-6666-4666-8666-666666666666",
                    dataset_pair_fingerprint=intent.expected_dataset_pair_fingerprint,
                    config_fingerprint=intent.expected_config_fingerprint,
                    readiness_fingerprint=intent.expected_readiness_fingerprint,
                    source_commit="a" * 40,
                    prerequisite_policy_reference="prerequisite-policy:c2-contract",
                )
            )
        with pytest.raises(Exception) as denied:
            with factory.transaction(
                isolation="REPEATABLE READ", read_only=True
            ) as restricted:
                restricted.execute(
                    f"SELECT count(*) FROM {SCHEMA}.training_authority_identity"
                )
        assert denied.value.sqlstate == "42501"
    finally:
        if prerequisite is not None:
            prerequisite.close()
        with c1_postgres.factory.connection() as owner:
            owner.execute("ALTER ROLE dohalm_training_resolver PASSWORD NULL")
            owner.commit()
