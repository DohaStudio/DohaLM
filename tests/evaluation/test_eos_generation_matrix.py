from __future__ import annotations

import copy

import pytest

from src.evaluation.eos_generation_matrix import (
    GENERATION_LENGTHS,
    GENERATION_PROFILE_IDS,
    EOSDiagnosticGenerationError,
    GenerationMatrix,
    GenerationProfile,
    supported_generation_profiles,
)


def _matrix() -> GenerationMatrix:
    return GenerationMatrix.create(
        matrix_id="synthetic-not-for-runtime-candidate-b-matrix-v1",
        profiles=supported_generation_profiles(),
    )


def test_exact_profiles_classification_counts_and_fingerprint_are_frozen() -> None:
    matrix = _matrix()
    assert (
        tuple(profile.profile_id for profile in matrix.profiles)
        == GENERATION_PROFILE_IDS
    )
    assert matrix.length_values == GENERATION_LENGTHS
    assert matrix.official_profile_ids == ("greedy",)
    assert matrix.diagnostic_profile_ids == GENERATION_PROFILE_IDS[1:]
    assert matrix.expected_execution_count == 15 * 11 * 4
    assert matrix.expected_trajectory_count == 15 * 11
    assert matrix.matrix_fingerprint == _matrix().matrix_fingerprint
    assert GenerationMatrix.from_mapping(matrix.as_dict()) == matrix


def test_profile_fingerprints_are_deterministic_and_length_axis_is_separate() -> None:
    profiles = supported_generation_profiles()
    assert profiles == supported_generation_profiles()
    assert all(profile.max_new_tokens is None for profile in profiles)
    assert len({profile.profile_fingerprint for profile in profiles}) == 11


@pytest.mark.parametrize(
    "overrides",
    [
        {"do_sample": True},
        {"temperature": 0.7},
        {"top_k": 20},
        {"top_p": 0.9},
        {"repetition_penalty": 1.05},
        {"no_repeat_ngram_size": 2},
        {"diagnostic_role": "diagnostic_only"},
    ],
)
def test_pure_greedy_rejects_sampling_or_assistance(
    overrides: dict[str, object],
) -> None:
    values = {
        "profile_id": "greedy",
        "mode": "pure_greedy",
        "do_sample": False,
        "temperature": None,
        "top_k": None,
        "top_p": None,
        "repetition_penalty": 1.0,
        "no_repeat_ngram_size": 0,
        "seed": 17,
        "diagnostic_role": "official_model_diagnostic",
    }
    values.update(overrides)
    with pytest.raises(
        EOSDiagnosticGenerationError, match="^EOS_DIAG_GENERATION_PROFILE_INVALID$"
    ):
        GenerationProfile.create(**values)


def test_sampling_requires_positive_temperature_valid_bounds_and_seed() -> None:
    base = supported_generation_profiles()[1].as_dict()
    for field, value in (
        ("temperature", 0),
        ("top_p", 1.1),
        ("top_k", 0),
        ("seed", -1),
    ):
        changed = {
            key: item
            for key, item in base.items()
            if key not in {"profile_fingerprint", "max_new_tokens"}
        }
        changed[field] = value
        with pytest.raises(
            EOSDiagnosticGenerationError, match="^EOS_DIAG_GENERATION_PROFILE_INVALID$"
        ):
            GenerationProfile.create(**changed)


def test_assisted_profiles_are_supported_but_external_heuristic_is_not() -> None:
    assert all(
        profile.mode == "assisted_decoding"
        for profile in supported_generation_profiles()[-4:]
    )
    value = supported_generation_profiles()[-1].as_dict()
    value["heuristic_stop"] = True
    with pytest.raises(
        EOSDiagnosticGenerationError, match="^EOS_DIAG_GENERATION_PROFILE_INVALID$"
    ):
        GenerationProfile.from_mapping(value)


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_profile", "missing_greedy", "unsupported_length", "profile_drift"],
)
def test_matrix_rejects_duplicate_missing_length_and_profile_drift(
    mutation: str,
) -> None:
    profiles = list(supported_generation_profiles())
    lengths = list(GENERATION_LENGTHS)
    if mutation == "duplicate_profile":
        profiles[-1] = profiles[-2]
    elif mutation == "missing_greedy":
        profiles = profiles[1:]
    elif mutation == "unsupported_length":
        lengths[-1] = 256
    else:
        profiles[1] = GenerationProfile.create(
            profile_id="temperature-0.7",
            mode="sampling",
            do_sample=True,
            temperature=0.8,
            top_k=None,
            top_p=None,
            repetition_penalty=1.0,
            no_repeat_ngram_size=0,
            seed=17,
            diagnostic_role="diagnostic_only",
        )
    with pytest.raises(
        EOSDiagnosticGenerationError, match="^EOS_DIAG_GENERATION_MATRIX_INVALID$"
    ):
        GenerationMatrix.create(
            matrix_id="synthetic-matrix", profiles=profiles, length_values=lengths
        )


def test_matrix_loader_rejects_unknown_field_and_fingerprint_tamper() -> None:
    value = _matrix().as_dict()
    value["unknown"] = True
    with pytest.raises(
        EOSDiagnosticGenerationError, match="^EOS_DIAG_GENERATION_MATRIX_INVALID$"
    ):
        GenerationMatrix.from_mapping(value)
    value = _matrix().as_dict()
    value["matrix_fingerprint"] = "sha256:" + "f" * 64
    with pytest.raises(
        EOSDiagnosticGenerationError, match="^EOS_DIAG_GENERATION_MATRIX_INVALID$"
    ):
        GenerationMatrix.from_mapping(value)


def test_matrix_loader_is_independent_of_mapping_insertion_order() -> None:
    value = _matrix().as_dict()
    reordered = {key: copy.deepcopy(value[key]) for key in reversed(tuple(value))}
    assert (
        GenerationMatrix.from_mapping(reordered).matrix_fingerprint
        == value["matrix_fingerprint"]
    )
