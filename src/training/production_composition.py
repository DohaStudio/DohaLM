"""Non-CLI C3 composition for PostgreSQL training authority adapters.

Import and construction are side-effect free.  The package-private root owns
configuration validation, role-scoped adapter construction, a non-mutating
preflight, guarded Host bootstrap, and deterministic shutdown.  It deliberately
does not expose an intent-intake or Training execution entrypoint.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from .errors import TrainingError
from .postgres_training_adapters import (
    _PostgresTrainingConnectionFactory,
    _PostgresTrainingConnectionSettings,
    _PostgresTrainingDecisionResolver,
    _PostgresTrainingExecutionJournal,
    _PostgresTrainingPrerequisiteResolver,
)
from .production_full_pretraining_host import (
    ProductionFullPretrainingHost,
    _bootstrap_production_full_pretraining_host,
)
from .production_host_foundation import (
    ProductionTrainingHostIntent,
    TrainingDecisionResolutionRequest,
)
from .production_orchestration_seams import (
    TrainingPrerequisiteResolutionRequest,
    _canonical_training_host_intent_fingerprint,
)


_POSTGRES_PROVIDER = "postgresql"
_DISABLED_PROVIDER = "disabled"
_RESOLVER_ROLE = "dohalm_training_resolver"
_JOURNAL_ROLE = "dohalm_training_journal"
_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}")
_APPLICATION_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,47}")
_FINGERPRINT = "sha256:" + "0" * 64


def _error(code: str, message: str) -> TrainingError:
    return TrainingError(code, message)


def _configuration_error() -> TrainingError:
    return _error(
        "TRAINING_COMPOSITION_CONFIGURATION_INVALID",
        "Valid redacted PostgreSQL composition configuration is required.",
    )


def _activation_error() -> TrainingError:
    return _error(
        "TRAINING_COMPOSITION_ACTIVATION_NOT_AUTHORIZED",
        "Explicit production training composition activation is required.",
    )


def _is_uuid(value: object) -> bool:
    if type(value) is not str:
        return False
    try:
        return str(UUID(value)) == value
    except ValueError:
        return False


@dataclass(frozen=True, slots=True, repr=False)
class _PostgresTrainingCompositionConfiguration:
    """Trusted immutable C3 configuration; never sourced from a raw DSN."""

    provider: str = _DISABLED_PROVIDER
    environment: str | None = None
    host: str | None = None
    port: int | None = None
    database: str | None = None
    resolver_password: str | None = None
    journal_password: str | None = None
    application_name: str | None = None
    process_boundary_id: str | None = None
    decision_authority_id: str | None = None
    prerequisite_policy_reference: str | None = None
    decision_policy_reference: str | None = None
    activation_authority_reference: str | None = None
    activation_evidence_reference: str | None = None
    connect_timeout_seconds: int | None = None
    statement_timeout_ms: int | None = None
    transaction_timeout_ms: int | None = None
    sslmode: str | None = None
    sslrootcert: Path | None = None

    def __post_init__(self) -> None:
        values = tuple(
            getattr(self, name)
            for name in self.__dataclass_fields__
            if name != "provider"
        )
        if self.provider == _DISABLED_PROVIDER:
            if any(value is not None for value in values):
                raise _configuration_error()
            return
        production_tls = (
            self.environment == "production"
            and self.sslmode == "verify-full"
            and isinstance(self.sslrootcert, Path)
            and self.sslrootcert.is_absolute()
            and self.sslrootcert.is_file()
            and not self.sslrootcert.is_symlink()
        )
        isolated_tls = (
            self.environment == "isolated_test"
            and self.host in {"127.0.0.1", "localhost"}
            and self.sslmode == "disable"
            and self.sslrootcert is None
        )
        references = (
            self.process_boundary_id,
            self.prerequisite_policy_reference,
            self.decision_policy_reference,
            self.activation_authority_reference,
            self.activation_evidence_reference,
        )
        if (
            self.provider != _POSTGRES_PROVIDER
            or not isinstance(self.host, str)
            or not self.host
            or type(self.port) is not int
            or not 1 <= self.port <= 65535
            or not isinstance(self.database, str)
            or _REFERENCE.fullmatch(self.database) is None
            or type(self.resolver_password) is not str
            or not self.resolver_password
            or type(self.journal_password) is not str
            or not self.journal_password
            or self.resolver_password == self.journal_password
            or not isinstance(self.application_name, str)
            or _APPLICATION_NAME.fullmatch(self.application_name) is None
            or not all(
                isinstance(value, str) and _REFERENCE.fullmatch(value) is not None
                for value in references
            )
            or not _is_uuid(self.decision_authority_id)
            or type(self.connect_timeout_seconds) is not int
            or not 1 <= self.connect_timeout_seconds <= 60
            or type(self.statement_timeout_ms) is not int
            or not 1 <= self.statement_timeout_ms <= 300_000
            or type(self.transaction_timeout_ms) is not int
            or not self.statement_timeout_ms <= self.transaction_timeout_ms <= 600_000
            or not (production_tls or isolated_tls)
        ):
            raise _configuration_error()

    def __repr__(self) -> str:
        return "_PostgresTrainingCompositionConfiguration(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class _ProductionTrainingActivationDecision:
    """Explicit trusted composition decision; configuration alone is not authority."""

    authorized: bool
    provider: str
    authority_reference: str
    evidence_reference: str
    process_boundary_id: str

    def __post_init__(self) -> None:
        if (
            type(self.authorized) is not bool
            or self.provider != _POSTGRES_PROVIDER
            or not all(
                type(value) is str and _REFERENCE.fullmatch(value) is not None
                for value in (
                    self.authority_reference,
                    self.evidence_reference,
                    self.process_boundary_id,
                )
            )
        ):
            raise _activation_error()

    def __repr__(self) -> str:
        return "_ProductionTrainingActivationDecision(<redacted>)"


@dataclass(frozen=True, slots=True)
class _PostgresTrainingPreflightResult:
    provider: str
    configuration_valid: bool
    resolver_connectivity: bool
    journal_connectivity: bool
    role_separation: bool
    mutation_count: int


class _PostgresTrainingComposition:
    """Construction-owned C3 lifecycle; no public execution boundary."""

    __slots__ = (
        "_configuration",
        "_decision_resolver",
        "_host",
        "_journal",
        "_journal_factory",
        "_lock",
        "_preflight_complete",
        "_prerequisite_resolver",
        "_resolver_factory",
        "_shutdown",
    )

    def __init__(
        self,
        configuration: _PostgresTrainingCompositionConfiguration,
        resolver_factory: _PostgresTrainingConnectionFactory,
        journal_factory: _PostgresTrainingConnectionFactory,
        prerequisite_resolver: _PostgresTrainingPrerequisiteResolver,
        decision_resolver: _PostgresTrainingDecisionResolver,
        journal: _PostgresTrainingExecutionJournal,
    ) -> None:
        self._configuration = configuration
        self._resolver_factory = resolver_factory
        self._journal_factory = journal_factory
        self._prerequisite_resolver = prerequisite_resolver
        self._decision_resolver = decision_resolver
        self._journal = journal
        self._host: ProductionFullPretrainingHost | None = None
        self._preflight_complete = False
        self._shutdown = False
        self._lock = threading.RLock()

    def __repr__(self) -> str:
        return "_PostgresTrainingComposition(<redacted>)"

    def preflight(self) -> _PostgresTrainingPreflightResult:
        """Run only restricted read paths; never claim, transition, or execute."""

        with self._lock:
            if self._shutdown:
                raise _error(
                    "TRAINING_COMPOSITION_SHUTDOWN",
                    "The production training composition is shut down.",
                )
            if self._preflight_complete:
                return self._preflight_result()
            intent, prerequisite_request, decision_request = self._probe_requests()
            try:
                resolved = self._prerequisite_resolver.resolve(prerequisite_request)
            except TrainingError as error:
                if error.code != "TRAINING_HOST_PREREQUISITE_UNAVAILABLE":
                    raise self._map_preflight_error(error) from None
            else:
                self._prerequisite_resolver.release(resolved)
            try:
                self._decision_resolver.resolve(decision_request)
            except TrainingError as error:
                if error.code != "TRAINING_EXECUTION_DECISION_UNAVAILABLE":
                    raise self._map_preflight_error(error) from None
            try:
                self._journal.read(intent.run_id)
            except TrainingError as error:
                raise self._map_preflight_error(error) from None
            self._preflight_complete = True
            return self._preflight_result()

    def startup(
        self, decision: _ProductionTrainingActivationDecision
    ) -> ProductionFullPretrainingHost:
        """Bootstrap the existing Host only after explicit matching authority."""

        with self._lock:
            if self._shutdown or not self._preflight_complete:
                raise _activation_error()
            if (
                type(decision) is not _ProductionTrainingActivationDecision
                or decision.authorized is not True
                or decision.provider != self._configuration.provider
                or decision.authority_reference
                != self._configuration.activation_authority_reference
                or decision.evidence_reference
                != self._configuration.activation_evidence_reference
                or decision.process_boundary_id
                != self._configuration.process_boundary_id
            ):
                raise _activation_error()
            if self._host is not None:
                return self._host
            try:
                host = _bootstrap_production_full_pretraining_host(
                    self._prerequisite_resolver,
                    self._decision_resolver,
                    self._journal,
                    process_boundary_id=self._configuration.process_boundary_id,
                    decision_authority_id=self._configuration.decision_authority_id,
                )
            except TrainingError:
                raise
            except Exception:
                raise _error(
                    "TRAINING_COMPOSITION_CONSTRUCTION_FAILED",
                    "The production training composition could not be installed.",
                ) from None
            self._host = host
            return host

    def shutdown(self) -> None:
        """Close composition-owned materialization state; safe to repeat."""

        with self._lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._prerequisite_resolver.close()

    def _preflight_result(self) -> _PostgresTrainingPreflightResult:
        return _PostgresTrainingPreflightResult(
            provider=self._configuration.provider,
            configuration_valid=True,
            resolver_connectivity=True,
            journal_connectivity=True,
            role_separation=(
                self._resolver_factory is not self._journal_factory
                and self._resolver_factory.role == _RESOLVER_ROLE
                and self._journal_factory.role == _JOURNAL_ROLE
            ),
            mutation_count=0,
        )

    def _probe_requests(
        self,
    ) -> tuple[
        ProductionTrainingHostIntent,
        TrainingPrerequisiteResolutionRequest,
        TrainingDecisionResolutionRequest,
    ]:
        seed = uuid5(
            NAMESPACE_URL,
            f"dohalm:c3-preflight:{self._configuration.process_boundary_id}",
        )
        values = tuple(
            str(uuid5(seed, name))
            for name in ("version", "manifest", "config", "readiness", "decision")
        )
        version, manifest, config, readiness, decision = values
        intent = ProductionTrainingHostIntent(
            action="full_pretraining",
            execution_mode="fresh",
            dataset_version_reference=f"dataset-version:{version}",
            dataset_manifest_reference=f"dataset-manifest:{manifest}",
            expected_dataset_pair_fingerprint=_FINGERPRINT,
            training_config_reference=f"config:{config}",
            expected_config_fingerprint=_FINGERPRINT,
            readiness_evidence_reference=f"readiness:{readiness}",
            expected_readiness_fingerprint=_FINGERPRINT,
            run_id=f"c3-preflight:{seed}",
            output_logical_root="experiments/c3-preflight",
            decision_evidence_reference=f"decision:{decision}",
        )
        prerequisite = TrainingPrerequisiteResolutionRequest(
            intent=intent,
            intent_fingerprint=_canonical_training_host_intent_fingerprint(intent),
            dataset_version_authority_id=version,
            dataset_manifest_authority_id=manifest,
            config_authority_id=config,
            readiness_authority_id=readiness,
        )
        decision_request = TrainingDecisionResolutionRequest(
            intent=intent,
            decision_authority_id=decision,
            request_fingerprint=_FINGERPRINT,
            dataset_version_id=f"dataset-version:{version}",
            dataset_manifest_id=f"dataset-manifest:{manifest}",
            dataset_pair_authority_id=str(uuid5(seed, "pair")),
            dataset_pair_fingerprint=_FINGERPRINT,
            config_fingerprint=_FINGERPRINT,
            readiness_fingerprint=_FINGERPRINT,
            source_commit="0" * 40,
            prerequisite_policy_reference=(
                self._configuration.prerequisite_policy_reference
            ),
        )
        return intent, prerequisite, decision_request

    @staticmethod
    def _map_preflight_error(error: TrainingError) -> TrainingError:
        if error.code == "TRAINING_DATABASE_PERMISSION_DENIED":
            code = "TRAINING_COMPOSITION_PERMISSION_DENIED"
        elif error.code == "TRAINING_DATABASE_TIMEOUT":
            code = "TRAINING_COMPOSITION_TIMEOUT"
        elif "UNAVAILABLE" in error.code:
            code = "TRAINING_COMPOSITION_DEPENDENCY_UNAVAILABLE"
        else:
            code = "TRAINING_COMPOSITION_PREFLIGHT_FAILED"
        return _error(code, "The redacted PostgreSQL preflight failed.")


def _role_settings(
    configuration: _PostgresTrainingCompositionConfiguration, role: str
) -> _PostgresTrainingConnectionSettings:
    password = (
        configuration.resolver_password
        if role == _RESOLVER_ROLE
        else configuration.journal_password
    )
    suffix = "resolver" if role == _RESOLVER_ROLE else "journal"
    return _PostgresTrainingConnectionSettings(
        environment=configuration.environment,
        host=configuration.host,
        port=configuration.port,
        database=configuration.database,
        user=role,
        password=password,
        role=role,
        application_name=f"{configuration.application_name}.{suffix}",
        connect_timeout_seconds=configuration.connect_timeout_seconds,
        statement_timeout_ms=configuration.statement_timeout_ms,
        transaction_timeout_ms=configuration.transaction_timeout_ms,
        sslmode=configuration.sslmode,
        sslrootcert=configuration.sslrootcert,
    )


def _compose_postgres_training_host(
    configuration: _PostgresTrainingCompositionConfiguration,
) -> _PostgresTrainingComposition:
    """Construct the C3 graph without connecting, registering, or executing."""

    if type(configuration) is not _PostgresTrainingCompositionConfiguration:
        raise _configuration_error()
    if configuration.provider == _DISABLED_PROVIDER:
        raise _error(
            "TRAINING_COMPOSITION_PROVIDER_DISABLED",
            "The PostgreSQL training provider is disabled by default.",
        )
    prerequisite: _PostgresTrainingPrerequisiteResolver | None = None
    try:
        resolver_factory = _PostgresTrainingConnectionFactory(
            _role_settings(configuration, _RESOLVER_ROLE)
        )
        journal_factory = _PostgresTrainingConnectionFactory(
            _role_settings(configuration, _JOURNAL_ROLE)
        )
        prerequisite = _PostgresTrainingPrerequisiteResolver(
            resolver_factory,
            policy_reference=configuration.prerequisite_policy_reference,
        )
        decision = _PostgresTrainingDecisionResolver(
            resolver_factory,
            policy_reference=configuration.decision_policy_reference,
        )
        journal = _PostgresTrainingExecutionJournal(journal_factory)
        return _PostgresTrainingComposition(
            configuration,
            resolver_factory,
            journal_factory,
            prerequisite,
            decision,
            journal,
        )
    except TrainingError:
        if prerequisite is not None:
            prerequisite.close()
        raise
    except Exception:
        if prerequisite is not None:
            prerequisite.close()
        raise _error(
            "TRAINING_COMPOSITION_CONSTRUCTION_FAILED",
            "The production training composition could not be constructed.",
        ) from None


__all__: list[str] = []
