"""Authenticated PostgreSQL adapters for ADR-034 authority boundaries."""

from __future__ import annotations

from contextlib import AbstractContextManager
import json
from datetime import datetime
from typing import Any, Protocol

from .current_evidence_snapshot import (
    CurrentEvidenceError,
    DatasetEvidence,
    DatasetGovernanceSnapshot,
    RightsReadModel,
    SourceToken,
)
from .checksums import canonical_json_bytes
from .dataset_governance import DatasetVersionIdentity
from .product_dataset_current_evidence import (
    CurrentEvidenceBinding,
    DatasetLifecycleStage,
)
from .rights_metadata_projection import AuthorityRightsMetadata, TypedRightsEvidence

_RIGHTS_READER_ROLE = "doharights_reader"
_COORDINATOR_ROLE = "dohalm_current_evidence_coordinator"
_RESOLVER_ROLE = "dohalm_current_evidence_resolver"
_CURRENT_USE_RIGHTS_COLUMNS = (
    "canonical_payload",
    "record_id",
    "record_fingerprint",
    "projection_revision",
    "source_token_fingerprint",
    "rights_status",
    "source_classification",
    "analysis_allowed",
    "derivative_generation_allowed",
    "retention",
    "consent_evidence_references",
    "jurisdiction",
    "reviewer_authority_id",
    "reviewed_at",
    "current_use_authorization",
    "typed_evidence_references",
)


class AuthenticatedConnectionFactory(Protocol):
    role: str

    def connection(self) -> AbstractContextManager[Any]: ...


class PostgresCurrentRightsAuthority:
    """Call only DohaRights owner-issued restricted read functions."""

    def __init__(
        self,
        connection_factory: AuthenticatedConnectionFactory,
        *,
        source_authority_id: str,
        source_schema_version: str = "rights-authority-v1",
    ) -> None:
        if connection_factory.role != _RIGHTS_READER_ROLE:
            raise CurrentEvidenceError("RIGHTS_READER_CONFIGURATION_INVALID")
        self._factory = connection_factory
        self._source_authority_id = source_authority_id
        self._source_schema_version = source_schema_version

    def get_current_rights(self, subject_id: str) -> RightsReadModel:
        try:
            with self._factory.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT * FROM doharights_v1.get_current_use_rights(%s::uuid)",
                        (subject_id,),
                    )
                    columns = tuple(item.name for item in cursor.description or ())
                    rows = cursor.fetchall()
        except Exception as exc:
            raise _mapped(exc) from None
        if len(rows) == 0:
            raise CurrentEvidenceError("RIGHTS_CURRENT_MISSING")
        if len(rows) != 1:
            raise CurrentEvidenceError("RIGHTS_MULTIPLE_CURRENT")
        try:
            if columns != _CURRENT_USE_RIGHTS_COLUMNS:
                raise ValueError
            row = dict(zip(columns, rows[0], strict=True))
            payload = row["canonical_payload"]
            _validate_current_use_projection(row, payload)
            source = payload["source_authority"]
            subject = payload["subject"]
            permissions = payload["permissions"]
            if (
                str(source["source_authority_id"]) != self._source_authority_id
                or source["schema_version"] != self._source_schema_version
                or str(subject["rights_subject_id"]) != subject_id
            ):
                raise ValueError
            token = SourceToken(
                source_authority_id=self._source_authority_id,
                schema_version="rights-source-token-v1",
                subject_id=subject_id,
                evidence_id=str(row["record_id"]),
                evidence_fingerprint=str(row["record_fingerprint"]).rstrip(),
                projection_revision=int(row["projection_revision"]),
                token_fingerprint=str(row["source_token_fingerprint"]).rstrip(),
            )
            return RightsReadModel(
                subject_id=subject_id,
                record_id=str(row["record_id"]),
                source_authority_id=self._source_authority_id,
                schema_version="rights-source-token-v1",
                internal_training=permissions["internal_training"] is True,
                commercial_use=permissions["commercial_use"] is True,
                redistribution=permissions["redistribution"] is True,
                model_publication=permissions["external_model_publication"] is True,
                record_fingerprint=str(row["record_fingerprint"]).rstrip(),
                token=token,
                metadata=_rights_metadata(payload),
            )
        except (KeyError, TypeError, ValueError, CurrentEvidenceError):
            raise CurrentEvidenceError("RIGHTS_RESPONSE_MALFORMED") from None

    def verify_currentness(self, token: SourceToken) -> bool:
        if token.source_authority_id != self._source_authority_id:
            raise CurrentEvidenceError("RIGHTS_SOURCE_AUTHORITY_MISMATCH")
        try:
            with self._factory.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(
                        "SELECT doharights_v1.verify_rights_token(%s::uuid,%s::uuid,%s,%s,%s)",
                        (
                            token.subject_id,
                            token.evidence_id,
                            token.evidence_fingerprint,
                            token.projection_revision,
                            token.token_fingerprint,
                        ),
                    )
                    rows = cursor.fetchall()
        except Exception as exc:
            raise _mapped(exc) from None
        if len(rows) != 1 or len(rows[0]) != 1 or type(rows[0][0]) is not bool:
            raise CurrentEvidenceError("RIGHTS_RESPONSE_MALFORMED")
        return rows[0][0]


class PostgresSnapshotAuthority:
    """Durable append-only snapshot and binding adapter."""

    def __init__(self, factory: AuthenticatedConnectionFactory) -> None:
        if factory.role not in {_COORDINATOR_ROLE, _RESOLVER_ROLE}:
            raise CurrentEvidenceError("SNAPSHOT_AUTHORITY_CONFIGURATION_INVALID")
        self._factory = factory

    def get_by_idempotency(
        self, idempotency_key: str
    ) -> DatasetGovernanceSnapshot | None:
        rows = self._call(
            "SELECT * FROM dohalm_dataset_governance_v1.read_current_evidence_snapshot_by_key(%s)",
            (idempotency_key,),
        )
        return None if not rows else _snapshot_from_row(rows)

    def put_if_absent(
        self, idempotency_key: str, snapshot: DatasetGovernanceSnapshot
    ) -> DatasetGovernanceSnapshot:
        if self._factory.role != _COORDINATOR_ROLE:
            raise CurrentEvidenceError("SNAPSHOT_AUTHORITY_PERMISSION_DENIED")
        payload = _snapshot_payload(snapshot)
        canonical = canonical_json_bytes(payload)
        rows = self._call(
            "SELECT * FROM dohalm_dataset_governance_v1.put_current_evidence_snapshot(%s,%s,%s,%s,%s::jsonb,%s,%s)",
            (
                snapshot.snapshot_id,
                idempotency_key,
                snapshot.snapshot_fingerprint,
                snapshot.proposal_fingerprint,
                json.dumps(payload),
                canonical,
                snapshot.captured_at,
            ),
        )
        return _snapshot_from_row(rows)

    def get(self, snapshot_id: str) -> DatasetGovernanceSnapshot:
        return _snapshot_from_row(
            self._call(
                "SELECT * FROM dohalm_dataset_governance_v1.read_current_evidence_snapshot(%s)",
                (snapshot_id,),
            )
        )

    def _call(self, sql: str, parameters: tuple[object, ...]) -> list[tuple[Any, ...]]:
        try:
            with self._factory.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, parameters)
                    rows = cursor.fetchall()
        except Exception as exc:
            raise _mapped(exc) from None
        if len(rows) > 1:
            raise CurrentEvidenceError("SNAPSHOT_AUTHORITY_CORRUPT")
        return rows


class PostgresCurrentEvidenceBindingAuthority:
    def __init__(self, factory: AuthenticatedConnectionFactory) -> None:
        if factory.role not in {_COORDINATOR_ROLE, _RESOLVER_ROLE}:
            raise CurrentEvidenceError("SNAPSHOT_AUTHORITY_CONFIGURATION_INVALID")
        self._factory = factory

    def bind(self, binding: CurrentEvidenceBinding) -> CurrentEvidenceBinding:
        if self._factory.role != _COORDINATOR_ROLE:
            raise CurrentEvidenceError("SNAPSHOT_AUTHORITY_PERMISSION_DENIED")
        identity = binding.identity
        self._execute(
            "SELECT dohalm_dataset_governance_v1.bind_current_evidence_lifecycle(%s,%s,%s,%s,%s,%s,%s)",
            (
                identity.object_id,
                identity.dataset_id,
                identity.dataset_version,
                binding.stage.value,
                binding.proposal_fingerprint,
                binding.snapshot_id,
                binding.snapshot_fingerprint,
            ),
        )
        return binding

    def read(
        self, identity: DatasetVersionIdentity, stage: DatasetLifecycleStage
    ) -> CurrentEvidenceBinding:
        rows = self._execute(
            "SELECT * FROM dohalm_dataset_governance_v1.read_current_evidence_lifecycle(%s,%s,%s,%s)",
            (
                identity.object_id,
                identity.dataset_id,
                identity.dataset_version,
                stage.value,
            ),
        )
        if len(rows) != 1:
            raise CurrentEvidenceError("CURRENT_EVIDENCE_BINDING_MISSING")
        return CurrentEvidenceBinding(
            identity,
            str(rows[0][0]).rstrip(),
            stage,
            str(rows[0][1]),
            str(rows[0][2]).rstrip(),
        )

    def resolve_snapshot_binding(
        self, readiness_authority_id: str, readiness_fingerprint: str
    ) -> tuple[str, str]:
        rows = self._execute(
            "SELECT * FROM dohalm_dataset_governance_v1.resolve_readiness_current_evidence(%s,%s)",
            (readiness_authority_id, readiness_fingerprint),
        )
        if len(rows) != 1:
            raise CurrentEvidenceError("CURRENT_EVIDENCE_BINDING_MISSING")
        return str(rows[0][0]), str(rows[0][1]).rstrip()

    def bind_readiness(
        self,
        readiness_authority_id: str,
        readiness_fingerprint: str,
        snapshot_id: str,
        snapshot_fingerprint: str,
    ) -> None:
        if self._factory.role != _COORDINATOR_ROLE:
            raise CurrentEvidenceError("SNAPSHOT_AUTHORITY_PERMISSION_DENIED")
        self._execute(
            "SELECT dohalm_dataset_governance_v1.bind_readiness_current_evidence(%s,%s,%s,%s)",
            (
                readiness_authority_id,
                readiness_fingerprint,
                snapshot_id,
                snapshot_fingerprint,
            ),
        )

    def _execute(
        self, sql: str, parameters: tuple[object, ...]
    ) -> list[tuple[Any, ...]]:
        try:
            with self._factory.connection() as connection:
                with connection.cursor() as cursor:
                    cursor.execute(sql, parameters)
                    return cursor.fetchall()
        except Exception as exc:
            raise _mapped(exc) from None


def _token_payload(token: SourceToken) -> dict[str, object]:
    return {
        "source_authority_id": token.source_authority_id,
        "schema_version": token.schema_version,
        "subject_id": token.subject_id,
        "evidence_id": token.evidence_id,
        "evidence_fingerprint": token.evidence_fingerprint,
        "projection_revision": token.projection_revision,
        "token_fingerprint": token.token_fingerprint,
    }


def _snapshot_payload(snapshot: DatasetGovernanceSnapshot) -> dict[str, object]:
    rights_payload: dict[str, object] = {
        "subject_id": snapshot.rights.subject_id,
        "record_id": snapshot.rights.record_id,
        "source_authority_id": snapshot.rights.source_authority_id,
        "schema_version": snapshot.rights.schema_version,
        "internal_training": snapshot.rights.internal_training,
        "commercial_use": snapshot.rights.commercial_use,
        "redistribution": snapshot.rights.redistribution,
        "model_publication": snapshot.rights.model_publication,
        "record_fingerprint": snapshot.rights.record_fingerprint,
        "token": _token_payload(snapshot.rights.token),
    }
    if snapshot.rights.metadata is not None:
        rights_payload["metadata"] = _rights_metadata_payload(snapshot.rights.metadata)
    return {
        "snapshot_id": snapshot.snapshot_id,
        "schema_version": snapshot.schema_version,
        "proposal_fingerprint": snapshot.proposal_fingerprint,
        "dataset_subject_id": snapshot.dataset_subject_id,
        "dataset_evidence": {
            "subject_id": snapshot.dataset_evidence.subject_id,
            "evidence_id": snapshot.dataset_evidence.evidence_id,
            "evidence_fingerprint": snapshot.dataset_evidence.evidence_fingerprint,
            "source_authority_id": snapshot.dataset_evidence.source_authority_id,
            "schema_version": snapshot.dataset_evidence.schema_version,
            "training_allowed": snapshot.dataset_evidence.training_allowed,
            "token": _token_payload(snapshot.dataset_evidence.token),
        },
        "rights_subject_id": snapshot.rights_subject_id,
        "rights": rights_payload,
        "captured_at": snapshot.captured_at.isoformat(),
        "coordinator_authority_id": snapshot.coordinator_authority_id,
        "snapshot_fingerprint": snapshot.snapshot_fingerprint,
    }


def _source_token(payload: dict[str, Any]) -> SourceToken:
    return SourceToken(**payload)


def _snapshot_from_row(rows: list[tuple[Any, ...]]) -> DatasetGovernanceSnapshot:
    if len(rows) != 1:
        raise CurrentEvidenceError("CURRENT_EVIDENCE_SNAPSHOT_MISSING")
    payload = rows[0][2]
    try:
        dataset = payload["dataset_evidence"]
        rights = payload["rights"]
        return DatasetGovernanceSnapshot(
            snapshot_id=payload["snapshot_id"],
            schema_version=payload["schema_version"],
            proposal_fingerprint=payload["proposal_fingerprint"],
            dataset_subject_id=payload["dataset_subject_id"],
            dataset_evidence=DatasetEvidence(
                dataset["subject_id"],
                dataset["evidence_id"],
                dataset["evidence_fingerprint"],
                dataset["source_authority_id"],
                dataset["schema_version"],
                dataset["training_allowed"],
                _source_token(dataset["token"]),
            ),
            rights_subject_id=payload["rights_subject_id"],
            rights=RightsReadModel(
                rights["subject_id"],
                rights["record_id"],
                rights["source_authority_id"],
                rights["schema_version"],
                rights["internal_training"],
                rights["commercial_use"],
                rights["redistribution"],
                rights["model_publication"],
                rights["record_fingerprint"],
                _source_token(rights["token"]),
                (
                    _rights_metadata(rights["metadata"])
                    if rights.get("metadata") is not None
                    else None
                ),
            ),
            captured_at=datetime.fromisoformat(payload["captured_at"]),
            coordinator_authority_id=payload["coordinator_authority_id"],
            snapshot_fingerprint=str(rows[0][1]).rstrip(),
        )
    except (KeyError, TypeError, ValueError):
        raise CurrentEvidenceError("SNAPSHOT_AUTHORITY_CORRUPT") from None


def _rights_metadata(payload: dict[str, Any]) -> AuthorityRightsMetadata:
    subject = payload["subject"]
    classification = payload["source_classification"]
    permissions = payload["permissions"]
    retention = payload["retention"]
    review = payload["review"]
    current_use = payload["current_use_authorization"]
    return AuthorityRightsMetadata(
        dataset_source_identity=subject["dataset_source_identity"],
        subject_kind=subject["kind"],
        bound_identity=subject["bound_identity"],
        rights_status=payload["status"],
        source_type=classification["source_type"],
        user_created=classification["user_created"],
        generated=classification["generated"],
        reference=classification["reference"],
        uploaded=classification["uploaded"],
        external=classification["external"],
        analysis_allowed=permissions["analysis"],
        derivative_generation_allowed=permissions["derivative_generation"],
        retention_mode=retention["mode"],
        retention_scope=retention["scope"],
        retention_expires_at=_optional_time(retention.get("expires_at")),
        consent_evidence_references=tuple(payload["consent_evidence_references"]),
        jurisdiction=payload["jurisdiction"],
        reviewer_authority_id=review["reviewer_authority_id"],
        reviewed_at=_time(review["reviewed_at"]),
        producer_authority_id=payload["producer_authority_id"],
        effective_at=_time(payload["effective_at"]),
        current_use_authorized=current_use["authorized"],
        current_use_scope=current_use["scope"],
        fresh_acquisition_required=current_use["fresh_acquisition_required"],
        existing_material_reuse=current_use["existing_material_reuse"],
        historical_acquisition_receipt=current_use["historical_acquisition_receipt"],
        provider_reacquisition_requirement_found=current_use[
            "provider_reacquisition_requirement_found"
        ],
        typed_evidence_references=tuple(
            TypedRightsEvidence(value["reference_id"], value["evidence_type"])
            for value in payload["evidence_references"]
        ),
    )


def _validate_current_use_projection(
    row: dict[str, Any], payload: dict[str, Any]
) -> None:
    if (
        type(payload) is not dict
        or any(row[name] is None for name in _CURRENT_USE_RIGHTS_COLUMNS)
        or type(row["projection_revision"]) is not int
        or row["projection_revision"] < 1
    ):
        raise ValueError
    permissions = payload["permissions"]
    review = payload["review"]
    expected = {
        "rights_status": payload["status"],
        "source_classification": payload["source_classification"],
        "analysis_allowed": permissions["analysis"],
        "derivative_generation_allowed": permissions["derivative_generation"],
        "retention": payload["retention"],
        "consent_evidence_references": payload["consent_evidence_references"],
        "jurisdiction": payload["jurisdiction"],
        "reviewer_authority_id": review["reviewer_authority_id"],
        "current_use_authorization": payload["current_use_authorization"],
        "typed_evidence_references": payload["evidence_references"],
    }
    for name, value in expected.items():
        actual = row[name]
        if name == "reviewer_authority_id":
            actual = str(actual)
        if actual != value:
            raise ValueError
    reviewed_at = row["reviewed_at"]
    if isinstance(reviewed_at, str):
        reviewed_at = _time(reviewed_at)
    if reviewed_at != _time(review["reviewed_at"]):
        raise ValueError


def _rights_metadata_payload(value: AuthorityRightsMetadata) -> dict[str, object]:
    return {
        "subject": {
            "dataset_source_identity": value.dataset_source_identity,
            "kind": value.subject_kind,
            "bound_identity": value.bound_identity,
        },
        "status": value.rights_status,
        "source_classification": {
            "source_type": value.source_type,
            "user_created": value.user_created,
            "generated": value.generated,
            "reference": value.reference,
            "uploaded": value.uploaded,
            "external": value.external,
        },
        "permissions": {
            "analysis": value.analysis_allowed,
            "derivative_generation": value.derivative_generation_allowed,
        },
        "retention": {
            "mode": value.retention_mode,
            "scope": value.retention_scope,
            "expires_at": (
                value.retention_expires_at.isoformat()
                if value.retention_expires_at is not None
                else None
            ),
        },
        "consent_evidence_references": list(value.consent_evidence_references),
        "jurisdiction": value.jurisdiction,
        "review": {
            "reviewer_authority_id": value.reviewer_authority_id,
            "reviewed_at": value.reviewed_at.isoformat(),
        },
        "producer_authority_id": value.producer_authority_id,
        "effective_at": value.effective_at.isoformat(),
        "current_use_authorization": {
            "authorized": value.current_use_authorized,
            "scope": value.current_use_scope,
            "fresh_acquisition_required": value.fresh_acquisition_required,
            "existing_material_reuse": value.existing_material_reuse,
            "historical_acquisition_receipt": value.historical_acquisition_receipt,
            "provider_reacquisition_requirement_found": (
                value.provider_reacquisition_requirement_found
            ),
        },
        "evidence_references": [
            {"reference_id": item.reference_id, "evidence_type": item.evidence_type}
            for item in value.typed_evidence_references
        ],
    }


def _time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError
    return parsed


def _optional_time(value: str | None) -> datetime | None:
    return None if value is None else _time(value)


def _mapped(error: BaseException) -> CurrentEvidenceError:
    state = getattr(error, "sqlstate", None)
    if state == "42501":
        return CurrentEvidenceError("RIGHTS_READER_AUTHORIZATION_FAILED")
    if state == "28P01":
        return CurrentEvidenceError("RIGHTS_READER_AUTHENTICATION_FAILED")
    return CurrentEvidenceError("RIGHTS_SOURCE_UNAVAILABLE")


__all__ = [
    "AuthenticatedConnectionFactory",
    "PostgresCurrentEvidenceBindingAuthority",
    "PostgresCurrentRightsAuthority",
    "PostgresSnapshotAuthority",
]
