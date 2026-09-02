"""Bounded manifest-reference authority for large Product Dataset proposals."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .candidate_a_allocation_fingerprint import (
    CONTRACT_VERSION as CANDIDATE_A_ALLOCATION_CONTRACT_VERSION,
)
from .candidate_a_allocation_fingerprint import (
    fingerprint_allocation,
)
from .checksums import canonical_json_bytes, checksum_value, sha256_bytes
from .dataset_governance import (
    DatasetGovernanceError,
    DatasetVersionProposal,
    propose_manifest_reference_dataset_version,
)
from .learning_candidate_consumer import CommonObjectReference, ProducerIdentity
from .product_dataset_composition import (
    ProductDatasetComposition,
    ProductDatasetCompositionMember,
    ProductDatasetCompositionStatus,
    build_dataset_version_proposal_mapping,
)

_SHA256_PREFIX = "sha256:"
_FILES = {
    "composition": "composition.json",
    "member_manifest": "members.jsonl",
    "dataset_manifest": "dataset-manifest.json",
    "allocation_manifest": "split-manifest.json",
}


class ProductDatasetManifestAuthorityError(RuntimeError):
    """Manifest-reference proposal material failed closed."""

    def __init__(self, code: str, stage: str) -> None:
        self.code = code
        self.stage = stage
        super().__init__(f"{code}:{stage}:product_dataset_manifest_authority")


@dataclass(frozen=True, slots=True)
class ManifestReference:
    """Content identity; a runtime path is deliberately not authority data."""

    logical_identity: str
    content_fingerprint: str
    byte_size: int
    schema_version: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "byte_size": self.byte_size,
            "content_fingerprint": self.content_fingerprint,
            "logical_identity": self.logical_identity,
            "schema_version": self.schema_version,
        }


@dataclass(frozen=True, slots=True)
class ManifestReferenceDatasetProposal:
    """Full validated proposal plus its bounded immutable authority root."""

    proposal: DatasetVersionProposal
    canonical_root: bytes
    proposal_fingerprint: str


class ProductDatasetManifestAuthority:
    """Verify immutable build artifacts and reproduce a full DatasetVersion."""

    def __init__(self, artifact_root: Path) -> None:
        if not isinstance(artifact_root, Path) or not artifact_root.is_absolute():
            raise ProductDatasetManifestAuthorityError(
                "MANIFEST_AUTHORITY_CONFIGURATION_INVALID", "configuration"
            )
        self._artifact_root = artifact_root.resolve()

    def __repr__(self) -> str:
        return "ProductDatasetManifestAuthority(<locator-redacted>)"

    def read_composition(self) -> ProductDatasetComposition:
        """Read the exact composition only after all bound manifests verify."""

        return _composition(self._verified_material()["composition"])

    def create_submission(
        self, composition: ProductDatasetComposition
    ) -> ManifestReferenceDatasetProposal:
        if type(composition) is not ProductDatasetComposition:
            raise ProductDatasetManifestAuthorityError(
                "COMPOSITION_INVALID", "submission"
            )
        material = self._verified_material()
        stored_composition = _composition(material["composition"])
        if stored_composition != composition:
            raise ProductDatasetManifestAuthorityError(
                "COMPOSITION_MISMATCH", "submission"
            )
        return self._submission(stored_composition, material)

    def resolve_root(self, canonical_root: bytes) -> DatasetVersionProposal:
        root = _canonical_root(canonical_root)
        material = self._verified_material(expected_root=root)
        composition = _composition(material["composition"])
        submission = self._submission(composition, material)
        if submission.canonical_root != canonical_root:
            raise ProductDatasetManifestAuthorityError(
                "PROPOSAL_ROOT_MISMATCH", "resolution"
            )
        return submission.proposal

    def _verified_material(
        self, *, expected_root: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        checksums = _json_object(self._artifact_root / "artifact-checksums.json")
        declared = checksums.get("files")
        if not isinstance(declared, dict):
            raise ProductDatasetManifestAuthorityError(
                "MANIFEST_CHECKSUM_AUTHORITY_INVALID", "verification"
            )
        material: dict[str, Any] = {}
        references: dict[str, ManifestReference] = {}
        for kind, name in _FILES.items():
            path = self._artifact_root / name
            expected = declared.get(name)
            actual, size = _file_identity(path)
            if expected != actual:
                raise ProductDatasetManifestAuthorityError(
                    "MANIFEST_FINGERPRINT_MISMATCH", kind
                )
            if kind == "member_manifest":
                material[kind] = path
                schema_version = "product-dataset-member-manifest-v1"
            else:
                material[kind] = _json_object(path)
                schema_version = str(material[kind].get("schema_version", "1.0.0"))
            references[kind] = ManifestReference(
                logical_identity=_logical_identity(kind, material),
                content_fingerprint=actual,
                byte_size=size,
                schema_version=schema_version,
            )
        material["references"] = references
        _verify_material(material)
        if expected_root is not None:
            for kind, reference in references.items():
                if expected_root.get(kind) != reference.to_dict():
                    raise ProductDatasetManifestAuthorityError(
                        "MANIFEST_REFERENCE_STALE", kind
                    )
        return material

    @staticmethod
    def _submission(
        composition: ProductDatasetComposition, material: dict[str, Any]
    ) -> ManifestReferenceDatasetProposal:
        references = material["references"]
        dataset_manifest = material["dataset_manifest"]
        allocation_manifest = material["allocation_manifest"]
        members = tuple(sorted(composition.members, key=lambda item: item.candidate_id))
        counts = {
            split: sum(member.split == split for member in members)
            for split in ("train", "validation", "test")
        }
        proposal_id = (
            "dataset-proposal-v2:"
            + checksum_value(
                {
                    "composition_id": composition.composition_id,
                    "dataset_id": composition.dataset_id,
                    "dataset_version": composition.dataset_version,
                    "object_id": composition.object_id,
                }
            )[7:]
        )
        root = {
            "schema_name": "dataset_version_proposal_root",
            "schema_version": "2.0.0",
            "proposal_id": proposal_id,
            "object_id": composition.object_id,
            "dataset_id": composition.dataset_id,
            "dataset_version": composition.dataset_version,
            "status": "draft",
            "created_at": composition.created_at,
            "producer": {
                "name": composition.producer.name,
                "version": composition.producer.version,
            },
            "composition_id": composition.composition_id,
            "composition_source_fingerprint": composition.source_fingerprint,
            "composition_content_fingerprint": composition.content_fingerprint,
            "composition": references["composition"].to_dict(),
            "member_manifest": references["member_manifest"].to_dict(),
            "dataset_manifest": references["dataset_manifest"].to_dict(),
            "allocation_manifest": references["allocation_manifest"].to_dict(),
            "member_count": len(members),
            "split_counts": counts,
            "allocation_fingerprint": allocation_manifest["allocation_fingerprint"],
            "production_dataset_fingerprint": dataset_manifest["dataset_fingerprint"],
            "current_rights_snapshot_reference": {
                "rights_metadata_id": dataset_manifest["rights_metadata_id"],
                "source_token_fingerprint": dataset_manifest[
                    "rights_source_token_fingerprint"
                ],
            },
            "eligibility_evidence_reference": (
                composition.dataset_eligibility_evidence_id
            ),
        }
        canonical_root = canonical_json_bytes(root)
        if len(canonical_root) >= 1_048_576:
            raise ProductDatasetManifestAuthorityError(
                "PROPOSAL_ROOT_TOO_LARGE", "submission"
            )
        payload = build_dataset_version_proposal_mapping(composition)
        try:
            proposal = propose_manifest_reference_dataset_version(
                payload, authority_root=root
            )
        except DatasetGovernanceError as exc:
            raise ProductDatasetManifestAuthorityError(
                "PROPOSAL_ROOT_INVALID", "submission"
            ) from exc
        return ManifestReferenceDatasetProposal(
            proposal=proposal,
            canonical_root=canonical_root,
            proposal_fingerprint=_SHA256_PREFIX
            + hashlib.sha256(canonical_root).hexdigest(),
        )


def _verify_material(material: dict[str, Any]) -> None:
    composition = _composition(material["composition"])
    dataset = material["dataset_manifest"]
    allocation = material["allocation_manifest"]
    expected_counts = {
        split: len(getattr(composition, f"{split}_members"))
        for split in ("train", "validation", "test")
    }
    actual_counts = {
        split: allocation.get("statistics", {}).get(split, {}).get("records")
        for split in expected_counts
    }
    if (
        dataset.get("dataset_id") != composition.dataset_id
        or dataset.get("dataset_manifest_id") != composition.dataset_manifest_id
        or dataset.get("identity", {}).get("composition_id")
        != composition.composition_id
        or dataset.get("identity", {}).get("composition_source_fingerprint")
        != composition.source_fingerprint
        or dataset.get("identity", {}).get("composition_content_fingerprint")
        != composition.content_fingerprint
        or dataset.get("identity", {}).get("split_counts") != expected_counts
        or actual_counts != expected_counts
        or allocation.get("cross_split_group_overlap") != 0
    ):
        raise ProductDatasetManifestAuthorityError(
            "MANIFEST_COMPOSITION_MISMATCH", "verification"
        )
    expected_by_id = {member.candidate_id: member for member in composition.members}
    seen: set[str] = set()
    allocation_rows: list[dict[str, str]] = []
    count = 0
    with material["member_manifest"].open("r", encoding="utf-8", newline="") as handle:
        for line in handle:
            try:
                actual = json.loads(line)
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise ProductDatasetManifestAuthorityError(
                    "MEMBER_MANIFEST_INVALID", "verification"
                ) from None
            candidate_id = (
                actual.get("candidate_id") if isinstance(actual, dict) else None
            )
            expected = expected_by_id.get(candidate_id)
            if expected is None:
                raise ProductDatasetManifestAuthorityError(
                    "MEMBER_MANIFEST_MISMATCH", "verification"
                )
            projection = {
                "candidate_id": expected.candidate_id,
                "content_fingerprint": expected.candidate_content_fingerprint,
                "group_key": expected.group_key,
                "handoff_id": expected.handoff_id,
                "source_id": "sha256:" + expected.candidate_id.rsplit(":", 1)[-1],
                "split": expected.split,
            }
            if actual != projection or expected.candidate_id in seen:
                raise ProductDatasetManifestAuthorityError(
                    "MEMBER_MANIFEST_MISMATCH", "verification"
                )
            seen.add(expected.candidate_id)
            allocation_rows.append(
                {
                    "source_id": projection["source_id"],
                    "group_key": projection["group_key"],
                    "split": projection["split"],
                }
            )
            count += 1
    if count != len(composition.members) or seen != set(expected_by_id):
        raise ProductDatasetManifestAuthorityError(
            "MEMBER_COUNT_MISMATCH", "verification"
        )
    try:
        contract_version = allocation["allocation_fingerprint_contract_version"]
        if contract_version == CANDIDATE_A_ALLOCATION_CONTRACT_VERSION:
            allocation_fingerprint = fingerprint_allocation(
                allocation_rows,
                contract_version=contract_version,
            )
            computed_fingerprint = allocation_fingerprint.fingerprint
            computed_size = allocation_fingerprint.canonical_bytes_size
            computed_count = allocation_fingerprint.allocation_count
        elif contract_version == "product-dataset-allocation-reference-v1":
            canonical = canonical_json_bytes(
                {
                    "contract_version": contract_version,
                    "allocations": sorted(
                        allocation_rows, key=lambda item: item["source_id"]
                    ),
                }
            )
            computed_fingerprint = sha256_bytes(canonical)
            computed_size = len(canonical)
            computed_count = len(allocation_rows)
        else:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        raise ProductDatasetManifestAuthorityError(
            "ALLOCATION_FINGERPRINT_MISMATCH", "verification"
        ) from None
    if (
        computed_fingerprint != allocation.get("allocation_fingerprint")
        or computed_size
        != allocation.get("allocation_fingerprint_canonical_bytes_size")
        or computed_count != len(composition.members)
        or checksum_value(dataset.get("identity")) != dataset.get("dataset_fingerprint")
    ):
        raise ProductDatasetManifestAuthorityError(
            "ALLOCATION_OR_DATASET_FINGERPRINT_MISMATCH", "verification"
        )


def _composition(value: Any) -> ProductDatasetComposition:
    if isinstance(value, ProductDatasetComposition):
        return value
    if not isinstance(value, dict):
        raise ProductDatasetManifestAuthorityError("COMPOSITION_INVALID", "decode")
    try:

        def producer(raw: dict[str, Any]) -> ProducerIdentity:
            return ProducerIdentity(raw["name"], raw["version"])

        def reference(raw: dict[str, Any]) -> CommonObjectReference:
            return CommonObjectReference(
                object_id=raw["object_id"],
                schema_name=raw["schema_name"],
                schema_version=raw["schema_version"],
                content_fingerprint=raw["content_fingerprint"],
            )

        def member(raw: dict[str, Any]) -> ProductDatasetCompositionMember:
            return ProductDatasetCompositionMember(
                handoff_id=raw["handoff_id"],
                candidate_id=raw["candidate_id"],
                candidate_schema_version=raw["candidate_schema_version"],
                candidate_content_fingerprint=raw["candidate_content_fingerprint"],
                review_evidence_reference=raw["review_evidence_reference"],
                reviewer_id=raw["reviewer_id"],
                reviewed_at=raw["reviewed_at"],
                split=raw["split"],
                group_key=raw["group_key"],
                source_type=raw["source_type"],
                task=raw["task"],
                usage_purpose=raw["usage_purpose"],
                workspace_id=raw["workspace_id"],
                rights_metadata_id=raw["rights_metadata_id"],
                training_eligibility_id=raw["training_eligibility_id"],
                candidate_producer=producer(raw["candidate_producer"]),
                rights_producer=producer(raw["rights_producer"]),
                eligibility_producer=producer(raw["eligibility_producer"]),
                input_references=tuple(
                    reference(item) for item in raw["input_references"]
                ),
                output_references=tuple(
                    reference(item) for item in raw["output_references"]
                ),
                parent_candidate_ids=tuple(raw["parent_candidate_ids"]),
                candidate_review_evidence_ids=tuple(
                    raw["candidate_review_evidence_ids"]
                ),
                consent_evidence_refs=tuple(raw["consent_evidence_refs"]),
            )

        return ProductDatasetComposition(
            composition_id=value["composition_id"],
            status=ProductDatasetCompositionStatus(value["status"]),
            object_id=value["object_id"],
            dataset_id=value["dataset_id"],
            dataset_version=value["dataset_version"],
            created_at=value["created_at"],
            composed_at=value["composed_at"],
            created_by=value["created_by"],
            producer=producer(value["producer"]),
            workspace_id=value["workspace_id"],
            schema_manifest_id=value["schema_manifest_id"],
            dataset_manifest_id=value["dataset_manifest_id"],
            dataset_eligibility_evidence_id=value["dataset_eligibility_evidence_id"],
            approval_evidence_ids=tuple(value["approval_evidence_ids"]),
            task=value["task"],
            usage_purpose=value["usage_purpose"],
            train_members=tuple(member(item) for item in value["train_members"]),
            validation_members=tuple(
                member(item) for item in value["validation_members"]
            ),
            test_members=tuple(member(item) for item in value["test_members"]),
            source_fingerprint=value["source_fingerprint"],
            content_fingerprint=value["content_fingerprint"],
            contract_package_version=value["contract_package_version"],
            contract_policy_version=value["contract_policy_version"],
            contract_authority_commit=value["contract_authority_commit"],
        )
    except (KeyError, TypeError, ValueError):
        raise ProductDatasetManifestAuthorityError(
            "COMPOSITION_INVALID", "decode"
        ) from None


def _logical_identity(kind: str, material: dict[str, Any]) -> str:
    if kind == "composition":
        return str(material[kind]["composition_id"])
    if kind == "dataset_manifest":
        return str(material[kind]["dataset_manifest_id"])
    if kind == "member_manifest":
        dataset = material.get("dataset_manifest")
        if not isinstance(dataset, dict):
            dataset = _json_object(
                Path(material[kind]).parent / "dataset-manifest.json"
            )
        return "member-manifest:" + str(dataset["dataset_manifest_id"])
    if kind == "allocation_manifest":
        return "allocation-manifest:aihub-71748-production-v1"
    raise AssertionError(kind)


def _canonical_root(value: bytes) -> dict[str, Any]:
    if type(value) is not bytes or len(value) >= 1_048_576:
        raise ProductDatasetManifestAuthorityError("PROPOSAL_ROOT_INVALID", "decode")
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ProductDatasetManifestAuthorityError(
            "PROPOSAL_ROOT_INVALID", "decode"
        ) from None
    if not isinstance(decoded, dict) or canonical_json_bytes(decoded) != value:
        raise ProductDatasetManifestAuthorityError("PROPOSAL_ROOT_INVALID", "decode")
    return decoded


def _json_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        raise ProductDatasetManifestAuthorityError(
            "MANIFEST_MISSING_OR_INVALID", "read"
        ) from None
    if not isinstance(value, dict):
        raise ProductDatasetManifestAuthorityError(
            "MANIFEST_MISSING_OR_INVALID", "read"
        )
    return value


def _file_identity(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    try:
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
    except OSError:
        raise ProductDatasetManifestAuthorityError(
            "MANIFEST_MISSING_OR_INVALID", "read"
        ) from None
    return _SHA256_PREFIX + digest.hexdigest(), size


__all__ = [
    "ManifestReference",
    "ManifestReferenceDatasetProposal",
    "ProductDatasetManifestAuthority",
    "ProductDatasetManifestAuthorityError",
]
