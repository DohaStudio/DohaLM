from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timezone
import importlib
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import time
from uuid import uuid4

import psycopg
from psycopg import sql
import pytest

from src.data.current_evidence_snapshot import CurrentEvidenceError
from src.data.postgres_current_evidence import (
    AuthenticatedCurrentRightsMetadataVerifier,
    PostgresCurrentRightsAuthority,
)
from src.data.rights_metadata_projection import project_common_rights_metadata

IMAGE = (
    "postgres:16.15-alpine@"
    "sha256:075f7ba66bc9b3ce7d6b8b635208ff61cd7cf1a67d71ec530eec5d7ae0cbe571"
)
EXPECTED_COLUMNS = (
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


def _docker(*arguments: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *arguments],
        check=check,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _free_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _wait_ready(dsn: str) -> None:
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        try:
            with psycopg.connect(dsn) as connection:
                connection.execute("SELECT 1")
            return
        except psycopg.OperationalError:
            time.sleep(0.25)
    raise AssertionError("DOHARIGHTS_EPHEMERAL_POSTGRES_NOT_READY")


class _ReaderConnections:
    role = "doharights_reader"

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    @contextmanager
    def connection(self):
        with psycopg.connect(self._dsn) as connection:
            yield connection


def _rights_modules(source_root: Path):
    package_root = source_root / "src"
    sys.path.insert(0, str(package_root))
    try:
        return (
            importlib.import_module("doharights.authority"),
            importlib.import_module("doharights.postgres"),
        )
    finally:
        sys.path.remove(str(package_root))


@pytest.mark.integration
def test_actual_doharights_migrations_issue_read_project_and_fail_closed() -> None:
    source_root_value = os.environ.get("DOHARIGHTS_SOURCE_ROOT")
    if not source_root_value:
        pytest.skip(
            "DOHARIGHTS_SOURCE_ROOT is required for cross-repository integration"
        )
    source_root = Path(source_root_value).resolve()
    migrations = source_root / "src" / "doharights" / "postgres_migrations"
    migration_files = (
        migrations / "0001_rights_authority.sql",
        migrations / "0002_current_use_rights.sql",
    )
    assert all(path.is_file() for path in migration_files)

    authority_module, postgres_module = _rights_modules(source_root)
    port = _free_port()
    password = secrets.token_hex(24)
    producer_password = secrets.token_hex(24)
    reader_password = secrets.token_hex(24)
    correlation = uuid4().hex
    container = f"dohalm-rights-contract-{correlation}"
    owner_dsn = f"postgresql://postgres:{password}@127.0.0.1:{port}/postgres"
    producer_dsn = (
        f"postgresql://rights_test_producer:{producer_password}"
        f"@127.0.0.1:{port}/postgres"
    )
    reader_dsn = (
        f"postgresql://rights_test_reader:{reader_password}@127.0.0.1:{port}/postgres"
    )
    _docker(
        "run",
        "--detach",
        "--name",
        container,
        "--label",
        f"com.dohastudio.rights-contract.correlation={correlation}",
        "--publish",
        f"127.0.0.1:{port}:5432",
        "--env",
        f"POSTGRES_PASSWORD={password}",
        "--health-cmd",
        "pg_isready -U postgres -d postgres",
        "--health-interval",
        "1s",
        "--health-timeout",
        "3s",
        "--health-retries",
        "30",
        IMAGE,
    )
    try:
        _wait_ready(owner_dsn)
        with psycopg.connect(owner_dsn, autocommit=True) as connection:
            for path in migration_files:
                connection.execute(path.read_text(encoding="utf-8"))
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier("rights_test_producer"),
                    sql.Literal(producer_password),
                )
            )
            connection.execute(
                sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                    sql.Identifier("rights_test_reader"),
                    sql.Literal(reader_password),
                )
            )
            connection.execute("GRANT doharights_producer TO rights_test_producer")
            connection.execute("GRANT doharights_reader TO rights_test_reader")

        now = datetime.now(timezone.utc)
        source = authority_module.SourceAuthority(uuid4())
        subject = authority_module.RightsSubject(
            uuid4(),
            "AIHUB-71748",
            authority_module.RightsSubjectKind.SOURCE_DATASET,
            "AIHUB-71748",
        )
        producer, reviewer = uuid4(), uuid4()
        record = authority_module.RightsRecord(
            record_id=uuid4(),
            source_authority=source,
            subject=subject,
            permissions=authority_module.RightsPermissions(
                True, False, False, False, True, True
            ),
            status=authority_module.RightsStatus.APPROVED_LIMITED,
            source_classification=authority_module.RightsSourceClassification(
                "external", False, False, False, False, True
            ),
            retention=authority_module.RightsRetention(
                True,
                authority_module.RightsRetentionMode.INDEFINITE_WHILE_CURRENT,
                "training",
            ),
            consent_evidence_references=(),
            jurisdiction="KR",
            review=authority_module.RightsReview(reviewer, now),
            current_use_authorization=authority_module.CurrentUseAuthorization(
                True,
                "internal_noncommercial_model_training_and_evaluation",
                False,
                True,
                authority_module.HistoricalAcquisitionReceiptState.NOT_RECOVERED,
                False,
            ),
            evidence_references=(
                authority_module.RightsEvidenceReference(
                    "evidence:current-policy",
                    authority_module.RightsEvidenceType.PROVIDER_USAGE_POLICY,
                    "AI-Hub",
                    "https://example.invalid/current-policy",
                    now,
                ),
            ),
            effective_at=now,
            provenance_references=("ADR-036",),
            producer_authority_id=producer,
        )
        owner = postgres_module.PostgresCurrentRightsAuthority(
            lambda: psycopg.connect(producer_dsn)
        )
        issued = owner.issue(
            authority_module.IssueRightsCommand(
                uuid4(), record, uuid4(), producer, now, "integration issue"
            )
        )

        with psycopg.connect(reader_dsn) as connection, connection.cursor() as cursor:
            cursor.execute(
                "SELECT * FROM doharights_v1.get_current_use_rights(%s::uuid)",
                (subject.rights_subject_id,),
            )
            assert (
                tuple(item.name for item in cursor.description or ())
                == EXPECTED_COLUMNS
            )
            assert len(cursor.fetchone()) == 16

        consumer = PostgresCurrentRightsAuthority(
            _ReaderConnections(reader_dsn),
            source_authority_id=str(source.source_authority_id),
        )
        current = consumer.get_current_rights(str(subject.rights_subject_id))
        assert current.record_id == str(record.record_id)
        assert current.record_fingerprint == record.fingerprint
        assert current.token.token_fingerprint == issued.source_token.token_fingerprint
        assert current.token.projection_revision == 1
        assert consumer.verify_currentness(current.token) is True
        assert (
            consumer.verify_currentness(replace(current.token, projection_revision=2))
            is False
        )
        assert (
            consumer.verify_currentness(
                replace(current.token, evidence_fingerprint="sha256:" + "8" * 64)
            )
            is False
        )
        assert (
            consumer.verify_currentness(
                replace(current.token, token_fingerprint="sha256:" + "8" * 64)
            )
            is False
        )
        assert (
            consumer.verify_currentness(replace(current.token, subject_id=str(uuid4())))
            is False
        )
        with pytest.raises(
            CurrentEvidenceError, match="RIGHTS_SOURCE_AUTHORITY_MISMATCH"
        ):
            consumer.verify_currentness(
                replace(current.token, source_authority_id=str(uuid4()))
            )
        common = project_common_rights_metadata(current)
        verifier = AuthenticatedCurrentRightsMetadataVerifier(consumer)
        assert common["training_allowed"] is True
        assert common["consent_evidence_refs"] == []
        assert common["retention_allowed"] is True
        assert verifier(common) is True

        replacement = replace(
            record,
            record_id=uuid4(),
            previous_record_id=record.record_id,
        )
        replaced = owner.replace(
            authority_module.ReplaceRightsCommand(
                uuid4(),
                record.record_id,
                replacement,
                uuid4(),
                uuid4(),
                producer,
                now,
                "integration replace",
            )
        )
        assert consumer.verify_currentness(current.token) is False
        assert verifier(common) is False
        replacement_read = consumer.get_current_rights(str(subject.rights_subject_id))
        assert replacement_read.record_id == str(replacement.record_id)
        assert replacement_read.token.projection_revision == 2
        assert (
            replacement_read.token.token_fingerprint
            == replaced.source_token.token_fingerprint
        )

        with psycopg.connect(producer_dsn) as connection:
            connection.execute(
                "SELECT * FROM doharights_v1.revoke_rights("
                "%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)",
                (
                    uuid4(),
                    "sha256:" + "9" * 64,
                    subject.rights_subject_id,
                    replacement.record_id,
                    uuid4(),
                    producer,
                    now,
                    "integration revoke",
                    json.dumps(["ADR-036"]),
                ),
            )
        assert consumer.verify_currentness(replacement_read.token) is False
        assert verifier(project_common_rights_metadata(replacement_read)) is False
        with pytest.raises(CurrentEvidenceError, match="RIGHTS_CURRENT_MISSING"):
            consumer.get_current_rights(str(subject.rights_subject_id))
    finally:
        _docker("rm", "--force", container, check=False)
