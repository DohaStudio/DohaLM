"""Immutable EOS-DIAG-R2 generation profile and matrix contracts.

The module validates explicit values only.  It does not read configuration,
load model assets, inspect the environment, or perform generation.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .eos_diagnostic_artifacts import diagnostic_fingerprint

EOS_DIAG_R2_SCHEMA_VERSION = 2
GENERATION_LENGTHS = (16, 32, 64, 128)
GENERATION_PROFILE_IDS = (
    "greedy",
    "temperature-0.7",
    "temperature-1.0",
    "top-k-20",
    "top-k-50",
    "top-p-0.9",
    "top-p-0.95",
    "repetition-1.05",
    "repetition-1.10",
    "no-repeat-bigram",
    "no-repeat-trigram",
)

_PROFILE_FIELDS = frozenset(
    {
        "profile_id",
        "mode",
        "max_new_tokens",
        "do_sample",
        "temperature",
        "top_k",
        "top_p",
        "repetition_penalty",
        "no_repeat_ngram_size",
        "seed",
        "diagnostic_role",
        "profile_fingerprint",
    }
)
_MATRIX_FIELDS = frozenset(
    {
        "schema_version",
        "matrix_id",
        "profiles",
        "length_values",
        "prompt_count",
        "prompt_repetitions",
        "expected_execution_count",
        "expected_trajectory_count",
        "official_profile_ids",
        "diagnostic_profile_ids",
        "device",
        "dtype",
        "seed_derivation",
        "matrix_fingerprint",
    }
)


class EOSDiagnosticGenerationError(RuntimeError):
    """Fail-closed error exposing only a stable, non-sensitive code."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _fail(code: str) -> None:
    raise EOSDiagnosticGenerationError(code)


def _strict_mapping(
    value: object, fields: frozenset[str], code: str
) -> Mapping[str, Any]:
    if type(value) is not dict or set(value) != fields:
        _fail(code)
    return value


def _fingerprint(value: object, code: str) -> str:
    if (
        type(value) is not str
        or len(value) != 71
        or not value.startswith("sha256:")
        or any(character not in "0123456789abcdef" for character in value[7:])
    ):
        _fail(code)
    return value


def _profile_semantic(profile: GenerationProfile) -> dict[str, object]:
    value = profile.as_dict()
    value.pop("profile_fingerprint")
    return value


@dataclass(frozen=True)
class GenerationProfile:
    profile_id: str
    mode: str
    max_new_tokens: None
    do_sample: bool
    temperature: float | None
    top_k: int | None
    top_p: float | None
    repetition_penalty: float
    no_repeat_ngram_size: int
    seed: int
    diagnostic_role: str
    profile_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "mode": self.mode,
            "max_new_tokens": self.max_new_tokens,
            "do_sample": self.do_sample,
            "temperature": self.temperature,
            "top_k": self.top_k,
            "top_p": self.top_p,
            "repetition_penalty": self.repetition_penalty,
            "no_repeat_ngram_size": self.no_repeat_ngram_size,
            "seed": self.seed,
            "diagnostic_role": self.diagnostic_role,
            "profile_fingerprint": self.profile_fingerprint,
        }

    @classmethod
    def create(
        cls,
        *,
        profile_id: str,
        mode: str,
        do_sample: bool,
        temperature: float | None,
        top_k: int | None,
        top_p: float | None,
        repetition_penalty: float,
        no_repeat_ngram_size: int,
        seed: int,
        diagnostic_role: str,
    ) -> GenerationProfile:
        values: dict[str, object] = {
            "profile_id": profile_id,
            "mode": mode,
            "max_new_tokens": None,
            "do_sample": do_sample,
            "temperature": temperature,
            "top_k": top_k,
            "top_p": top_p,
            "repetition_penalty": repetition_penalty,
            "no_repeat_ngram_size": no_repeat_ngram_size,
            "seed": seed,
            "diagnostic_role": diagnostic_role,
        }
        _validate_profile_values(values)
        return cls(**values, profile_fingerprint=diagnostic_fingerprint(values))  # type: ignore[arg-type]

    @classmethod
    def from_mapping(cls, value: object) -> GenerationProfile:
        mapping = _strict_mapping(
            value, _PROFILE_FIELDS, "EOS_DIAG_GENERATION_PROFILE_INVALID"
        )
        profile = cls.create(
            profile_id=mapping["profile_id"],
            mode=mapping["mode"],
            do_sample=mapping["do_sample"],
            temperature=mapping["temperature"],
            top_k=mapping["top_k"],
            top_p=mapping["top_p"],
            repetition_penalty=mapping["repetition_penalty"],
            no_repeat_ngram_size=mapping["no_repeat_ngram_size"],
            seed=mapping["seed"],
            diagnostic_role=mapping["diagnostic_role"],
        )
        if mapping["max_new_tokens"] is not None:
            _fail("EOS_DIAG_GENERATION_PROFILE_INVALID")
        if (
            _fingerprint(
                mapping["profile_fingerprint"], "EOS_DIAG_GENERATION_PROFILE_INVALID"
            )
            != profile.profile_fingerprint
        ):
            _fail("EOS_DIAG_GENERATION_PROFILE_INVALID")
        return profile


def _validate_profile_values(value: Mapping[str, object]) -> None:
    code = "EOS_DIAG_GENERATION_PROFILE_INVALID"
    if (
        type(value["profile_id"]) is not str
        or value["profile_id"] not in GENERATION_PROFILE_IDS
    ):
        _fail(code)
    if value["mode"] not in {"pure_greedy", "sampling", "assisted_decoding"}:
        _fail(code)
    if (
        type(value["do_sample"]) is not bool
        or type(value["seed"]) is not int
        or value["seed"] < 0
    ):
        _fail(code)
    for field in ("temperature", "top_p", "repetition_penalty"):
        item = value[field]
        if item is not None and (
            type(item) not in {int, float} or isinstance(item, bool)
        ):
            _fail(code)
    if value["top_k"] is not None and (
        type(value["top_k"]) is not int or value["top_k"] <= 0
    ):
        _fail(code)
    if value["top_p"] is not None and not 0 < float(value["top_p"]) <= 1:
        _fail(code)
    if (
        type(value["no_repeat_ngram_size"]) is not int
        or value["no_repeat_ngram_size"] < 0
    ):
        _fail(code)
    if float(value["repetition_penalty"]) < 1:
        _fail(code)
    if value["diagnostic_role"] not in {"official_model_diagnostic", "diagnostic_only"}:
        _fail(code)
    if value["mode"] == "pure_greedy":
        valid = (
            value["do_sample"] is False
            and value["temperature"] is None
            and value["top_k"] is None
            and value["top_p"] is None
            and value["repetition_penalty"] == 1.0
            and value["no_repeat_ngram_size"] == 0
            and value["diagnostic_role"] == "official_model_diagnostic"
        )
    elif value["mode"] == "sampling":
        valid = (
            value["do_sample"] is True
            and value["temperature"] is not None
            and float(value["temperature"]) > 0
            and value["repetition_penalty"] == 1.0
            and value["no_repeat_ngram_size"] == 0
            and value["diagnostic_role"] == "diagnostic_only"
        )
    else:
        valid = (
            value["do_sample"] is False
            and value["temperature"] is None
            and value["top_k"] is None
            and value["top_p"] is None
            and (
                float(value["repetition_penalty"]) > 1.0
                or int(value["no_repeat_ngram_size"]) > 0
            )
            and value["diagnostic_role"] == "diagnostic_only"
        )
    if not valid:
        _fail(code)


def supported_generation_profiles(seed: int = 17) -> tuple[GenerationProfile, ...]:
    """Return the exact eleven profiles supported by the existing decoder."""
    specifications = (
        (
            "greedy",
            "pure_greedy",
            False,
            None,
            None,
            None,
            1.0,
            0,
            "official_model_diagnostic",
        ),
        (
            "temperature-0.7",
            "sampling",
            True,
            0.7,
            None,
            None,
            1.0,
            0,
            "diagnostic_only",
        ),
        (
            "temperature-1.0",
            "sampling",
            True,
            1.0,
            None,
            None,
            1.0,
            0,
            "diagnostic_only",
        ),
        ("top-k-20", "sampling", True, 1.0, 20, None, 1.0, 0, "diagnostic_only"),
        ("top-k-50", "sampling", True, 1.0, 50, None, 1.0, 0, "diagnostic_only"),
        ("top-p-0.9", "sampling", True, 1.0, None, 0.9, 1.0, 0, "diagnostic_only"),
        ("top-p-0.95", "sampling", True, 1.0, None, 0.95, 1.0, 0, "diagnostic_only"),
        (
            "repetition-1.05",
            "assisted_decoding",
            False,
            None,
            None,
            None,
            1.05,
            0,
            "diagnostic_only",
        ),
        (
            "repetition-1.10",
            "assisted_decoding",
            False,
            None,
            None,
            None,
            1.10,
            0,
            "diagnostic_only",
        ),
        (
            "no-repeat-bigram",
            "assisted_decoding",
            False,
            None,
            None,
            None,
            1.0,
            2,
            "diagnostic_only",
        ),
        (
            "no-repeat-trigram",
            "assisted_decoding",
            False,
            None,
            None,
            None,
            1.0,
            3,
            "diagnostic_only",
        ),
    )
    return tuple(
        GenerationProfile.create(
            profile_id=item[0],
            mode=item[1],
            do_sample=item[2],
            temperature=item[3],
            top_k=item[4],
            top_p=item[5],
            repetition_penalty=item[6],
            no_repeat_ngram_size=item[7],
            seed=seed,
            diagnostic_role=item[8],
        )
        for item in specifications
    )


@dataclass(frozen=True)
class GenerationMatrix:
    schema_version: int
    matrix_id: str
    profiles: tuple[GenerationProfile, ...]
    length_values: tuple[int, ...]
    prompt_count: int
    prompt_repetitions: int
    expected_execution_count: int
    expected_trajectory_count: int
    official_profile_ids: tuple[str, ...]
    diagnostic_profile_ids: tuple[str, ...]
    device: str
    dtype: str
    seed_derivation: str
    matrix_fingerprint: str

    def as_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "matrix_id": self.matrix_id,
            "profiles": [profile.as_dict() for profile in self.profiles],
            "length_values": list(self.length_values),
            "prompt_count": self.prompt_count,
            "prompt_repetitions": self.prompt_repetitions,
            "expected_execution_count": self.expected_execution_count,
            "expected_trajectory_count": self.expected_trajectory_count,
            "official_profile_ids": list(self.official_profile_ids),
            "diagnostic_profile_ids": list(self.diagnostic_profile_ids),
            "device": self.device,
            "dtype": self.dtype,
            "seed_derivation": self.seed_derivation,
            "matrix_fingerprint": self.matrix_fingerprint,
        }

    @classmethod
    def create(
        cls,
        *,
        matrix_id: str,
        profiles: Sequence[GenerationProfile],
        length_values: Sequence[int] = GENERATION_LENGTHS,
        prompt_count: int = 15,
        prompt_repetitions: int = 1,
        device: str = "cuda",
        dtype: str = "fp16",
        seed_derivation: str = "sha256-base-profile-opaque-prompt-id",
    ) -> GenerationMatrix:
        profile_tuple = tuple(profiles)
        length_tuple = tuple(length_values)
        if (
            type(matrix_id) is not str
            or not matrix_id
            or any(character in matrix_id for character in "\\/\n\r")
        ):
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        if type(prompt_count) is not int or prompt_count <= 0 or prompt_count != 15:
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        if type(prompt_repetitions) is not int or prompt_repetitions != 1:
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        if length_tuple != GENERATION_LENGTHS:
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        if (
            tuple(profile.profile_id for profile in profile_tuple)
            != GENERATION_PROFILE_IDS
        ):
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        expected_profiles = supported_generation_profiles(profile_tuple[0].seed)
        if tuple(_profile_semantic(item) for item in profile_tuple) != tuple(
            _profile_semantic(item) for item in expected_profiles
        ):
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        if (
            type(device) is not str
            or device != "cuda"
            or type(dtype) is not str
            or dtype != "fp16"
        ):
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        if seed_derivation != "sha256-base-profile-opaque-prompt-id":
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        official = ("greedy",)
        diagnostic = GENERATION_PROFILE_IDS[1:]
        logical_count = (
            prompt_count * len(profile_tuple) * len(length_tuple) * prompt_repetitions
        )
        trajectory_count = prompt_count * len(profile_tuple) * prompt_repetitions
        values: dict[str, object] = {
            "schema_version": EOS_DIAG_R2_SCHEMA_VERSION,
            "matrix_id": matrix_id,
            "profiles": [profile.as_dict() for profile in profile_tuple],
            "length_values": list(length_tuple),
            "prompt_count": prompt_count,
            "prompt_repetitions": prompt_repetitions,
            "expected_execution_count": logical_count,
            "expected_trajectory_count": trajectory_count,
            "official_profile_ids": list(official),
            "diagnostic_profile_ids": list(diagnostic),
            "device": device,
            "dtype": dtype,
            "seed_derivation": seed_derivation,
        }
        return cls(
            schema_version=EOS_DIAG_R2_SCHEMA_VERSION,
            matrix_id=matrix_id,
            profiles=profile_tuple,
            length_values=length_tuple,
            prompt_count=prompt_count,
            prompt_repetitions=prompt_repetitions,
            expected_execution_count=logical_count,
            expected_trajectory_count=trajectory_count,
            official_profile_ids=official,
            diagnostic_profile_ids=diagnostic,
            device=device,
            dtype=dtype,
            seed_derivation=seed_derivation,
            matrix_fingerprint=diagnostic_fingerprint(values),
        )

    @classmethod
    def from_mapping(cls, value: object) -> GenerationMatrix:
        mapping = _strict_mapping(
            value, _MATRIX_FIELDS, "EOS_DIAG_GENERATION_MATRIX_INVALID"
        )
        if (
            mapping["schema_version"] != EOS_DIAG_R2_SCHEMA_VERSION
            or type(mapping["profiles"]) is not list
        ):
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        matrix = cls.create(
            matrix_id=mapping["matrix_id"],
            profiles=tuple(
                GenerationProfile.from_mapping(item) for item in mapping["profiles"]
            ),
            length_values=mapping["length_values"],
            prompt_count=mapping["prompt_count"],
            prompt_repetitions=mapping["prompt_repetitions"],
            device=mapping["device"],
            dtype=mapping["dtype"],
            seed_derivation=mapping["seed_derivation"],
        )
        if matrix.as_dict() != dict(mapping):
            _fail("EOS_DIAG_GENERATION_MATRIX_INVALID")
        _fingerprint(
            mapping["matrix_fingerprint"], "EOS_DIAG_GENERATION_MATRIX_INVALID"
        )
        return matrix
