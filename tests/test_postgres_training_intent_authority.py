"""C2-owned durable PostgreSQL integration for the ADR-032 foundation."""

from __future__ import annotations

import pytest

from test_postgres_c1_integration import (
    C1Fixture,
    c1_postgres,
    check_training_intent_binding_validation_immutability_and_role_boundaries,
    check_training_intent_exact_conflicting_concurrent_and_cross_submitter_replay,
)


@pytest.mark.integration
def test_training_intent_exact_conflicting_concurrent_and_cross_submitter_replay(
    c1_postgres: C1Fixture,
) -> None:
    check_training_intent_exact_conflicting_concurrent_and_cross_submitter_replay(
        c1_postgres
    )


@pytest.mark.integration
def test_training_intent_binding_validation_immutability_and_role_boundaries(
    c1_postgres: C1Fixture,
) -> None:
    check_training_intent_binding_validation_immutability_and_role_boundaries(
        c1_postgres
    )


__all__ = ["c1_postgres"]
