from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.evaluation.eos_diagnostic_artifacts import (
    EXACT_ARTIFACT_FILENAMES,
    EOSDiagnosticArtifactError,
    diagnostic_fingerprint,
    new_diagnostic_artifact,
)
from src.evaluation.eos_diagnostic_identity import (
    BackendIdentity,
    CandidateBEvaluationBinding,
    CheckpointIdentity,
    DependencyIdentity,
    PromptSetIdentity,
    TokenizerIdentity,
)
from src.evaluation.eos_diagnostic_preflight import (
    BackendModuleSpec,
    DependencyRequirement,
    EOSDiagnosticPreflightError,
    GitCommandResult,
    InputRootSpec,
    LocalPreflightPaths,
    StaticPreflightRequest,
    build_backend_identity,
    build_dependency_identity,
    build_diagnostic_plan_preflight_section,
    run_static_preflight,
    validate_input_roots,
    validate_output_destinations,
    validate_repository_state,
)
from src.evaluation.eos_generation_matrix import (
    GenerationMatrix,
    supported_generation_profiles,
)

FP = lambda character: "sha256:" + character * 64
SHA = "1" * 40
RUN_ID = "SYNTHETIC-DOHALM-CANDIDATE-B-EOS-DIAGNOSTIC-20990101-0003"


def checkpoint(**overrides: object) -> CheckpointIdentity:
    values: dict[str, object] = {
        "checkpoint_id": "synthetic-candidate-b-final",
        "checkpoint_step": 12208,
        "checkpoint_checksum": FP("1"),
        "checkpoint_manifest_fingerprint": FP("2"),
        "model_config_fingerprint": FP("3"),
        "training_run_id": "SYNTHETIC-FULL-PRETRAIN-CANDIDATE-B-20990101-0001",
        "training_source_commit": SHA,
        "evaluation_id": "synthetic-candidate-b-full",
        "evaluation_fingerprint": FP("4"),
        "architecture_id": "DohaLM-Tiny",
        "parameter_count": 16889856,
        "dtype_contract": "cuda-fp16-evaluation-only",
        "immutable": True,
    }
    values.update(overrides)
    return CheckpointIdentity.create(**values)


def tokenizer() -> TokenizerIdentity:
    return TokenizerIdentity.create(
        tokenizer_id="synthetic-operating-16k-v2:unigram-16k",
        tokenizer_version="v2",
        tokenizer_fingerprint=FP("5"),
        tokenizer_manifest_checksum=FP("6"),
        model_checksum=FP("7"),
        vocab_checksum=FP("8"),
        vocabulary_size=16000,
        pad_token_id=0,
        bos_token_id=2,
        eos_token_id=3,
        unk_token_id=1,
        tokenizer_type="unigram",
        normalization_policy="identity",
        round_trip_status="verified",
        unknown_rate_status="verified",
        source_commit=SHA,
        compatibility_fingerprint=FP("9"),
    )


def prompt(**overrides: object) -> PromptSetIdentity:
    values: dict[str, object] = {
        "prompt_set_id": "synthetic-candidate-b-prompts",
        "prompt_set_version": "v1",
        "prompt_fingerprint": FP("a"),
        "prompt_count": 15,
        "category_counts": {f"category-{index:02d}": 1 for index in range(15)},
        "context_class_counts": {"minimal": 1, "short": 12, "medium": 1, "long": 1},
        "token_length_distribution": {"1-32": 8, "33-64": 5, "65-128": 2},
        "normalization_policy": "identity",
        "pii_status": "synthetic_pii_free",
        "leakage_status": "synthetic_no_dataset_source",
        "source_evidence_id": "synthetic-prompt-evidence",
        "source_evidence_fingerprint": FP("b"),
        "immutable": True,
    }
    values.update(overrides)
    return PromptSetIdentity.create(**values)


def backend(**overrides: object) -> BackendIdentity:
    values: dict[str, object] = {
        "backend_name": "synthetic-eos-diagnostic-backend",
        "backend_version": "r3",
        "source_commit": SHA,
        "module_fingerprints": {"preflight": FP("c")},
        "config_schema_version": "2",
        "artifact_schema_version": "1",
    }
    values.update(overrides)
    return BackendIdentity.create(**values)


def dependency(**overrides: object) -> DependencyIdentity:
    values: dict[str, object] = {
        "python_version": "3.12.1",
        "torch_version": "2.7.1+cu128",
        "cuda_build": "12.8",
        "cudnn_version": "9.7",
        "platform": "synthetic-win-amd64",
        "dependency_entries": [
            {
                "name": "torch",
                "version": "2.7.1+cu128",
                "required": True,
                "source": "installed-metadata",
            }
        ],
    }
    values.update(overrides)
    return DependencyIdentity.create(**values)


def matrix() -> GenerationMatrix:
    return GenerationMatrix.create(
        matrix_id="synthetic-candidate-b-matrix",
        profiles=supported_generation_profiles(),
    )


def binding(
    checkpoint_identity: CheckpointIdentity,
    tokenizer_identity: TokenizerIdentity,
    prompt_identity: PromptSetIdentity,
) -> CandidateBEvaluationBinding:
    return CandidateBEvaluationBinding(
        training_run_id=checkpoint_identity.training_run_id,
        checkpoint_checksum=checkpoint_identity.checkpoint_checksum,
        model_config_fingerprint=checkpoint_identity.model_config_fingerprint,
        evaluation_id=checkpoint_identity.evaluation_id,
        evaluation_fingerprint=checkpoint_identity.evaluation_fingerprint,
        architecture_id=checkpoint_identity.architecture_id,
        parameter_count=checkpoint_identity.parameter_count,
        tokenizer_fingerprint=tokenizer_identity.tokenizer_fingerprint,
        tokenizer_compatibility_fingerprint=tokenizer_identity.compatibility_fingerprint,
        prompt_fingerprint=prompt_identity.prompt_fingerprint,
        training_source_commit=checkpoint_identity.training_source_commit,
    )


def request(
    checkpoint_identity: CheckpointIdentity | None = None,
    tokenizer_identity: TokenizerIdentity | None = None,
    prompt_identity: PromptSetIdentity | None = None,
    backend_identity: BackendIdentity | None = None,
    dependency_identity: DependencyIdentity | None = None,
    generation_matrix: GenerationMatrix | None = None,
    **overrides: object,
) -> StaticPreflightRequest:
    checkpoint_identity = checkpoint_identity or checkpoint()
    tokenizer_identity = tokenizer_identity or tokenizer()
    prompt_identity = prompt_identity or prompt()
    backend_identity = backend_identity or backend()
    dependency_identity = dependency_identity or dependency()
    generation_matrix = generation_matrix or matrix()
    values: dict[str, object] = {
        "diagnostic_run_id": RUN_ID,
        "checkpoint_identity_fingerprint": checkpoint_identity.identity_fingerprint,
        "tokenizer_identity_fingerprint": tokenizer_identity.identity_fingerprint,
        "prompt_set_identity_fingerprint": prompt_identity.identity_fingerprint,
        "generation_matrix_fingerprint": generation_matrix.matrix_fingerprint,
        "backend_identity_fingerprint": backend_identity.backend_fingerprint,
        "dependency_identity_fingerprint": dependency_identity.dependency_fingerprint,
        "source_commit": SHA,
        "expected_branch": "develop",
        "expected_remote": "https://github.com/DohaStudio/DohaLM.git",
        "checkpoint_root_logical_id": "external/checkpoint/candidate-b-final",
        "tokenizer_root_logical_id": "external/tokenizer/operating-v2",
        "prompt_root_logical_id": "external/prompts/candidate-b-v1",
        "output_root_logical_id": "external/eos/r3/output",
        "staging_root_logical_id": "external/eos/r3/staging",
        "failure_root_logical_id": "external/eos/r3/failure",
        "expected_artifact_set_fingerprint": diagnostic_fingerprint(
            list(EXACT_ARTIFACT_FILENAMES)
        ),
        "minimum_free_disk_bytes": 1024,
        "maximum_path_length": 512,
        "lock_identity": "synthetic-r3-lock",
    }
    values.update(overrides)
    return StaticPreflightRequest.create(**values)


def git_runner(**overrides: str):
    values = {
        ("branch", "--show-current"): "develop",
        ("rev-parse", "HEAD"): SHA,
        ("rev-parse", "origin/develop"): SHA,
        ("remote", "get-url", "origin"): "https://github.com/DohaStudio/DohaLM.git",
        ("status", "--porcelain=v1", "--untracked-files=all"): "",
        ("rev-parse", "--git-dir"): ".git",
    }
    values.update({tuple(key.split(" ")): value for key, value in overrides.items()})

    def run(_root: Path, arguments: tuple[str, ...]) -> GitCommandResult:
        return GitCommandResult(0, values[arguments])

    return run


def make_paths(tmp_path: Path) -> tuple[LocalPreflightPaths, tuple[InputRootSpec, ...]]:
    repository = tmp_path / "repo"
    repository.mkdir()
    (repository / ".git").mkdir()
    specs = []
    roots = []
    for kind, logical_id, metadata in (
        ("checkpoint", "external/checkpoint/candidate-b-final", "manifest.json"),
        ("tokenizer", "external/tokenizer/operating-v2", "tokenizer-manifest.json"),
        ("prompt", "external/prompts/candidate-b-v1", "prompt-manifest.json"),
    ):
        root = tmp_path / kind
        root.mkdir()
        (root / metadata).write_text("synthetic metadata not parsed", encoding="utf-8")
        roots.append(root)
        specs.append(InputRootSpec(kind, logical_id, root, metadata))
    output_parent = tmp_path / "external-output"
    output_parent.mkdir()
    paths = LocalPreflightPaths(
        repository,
        roots[0],
        roots[1],
        roots[2],
        output_parent / "final",
        output_parent / "staging",
        output_parent / "failure",
        output_parent / "diagnostic.lock",
    )
    return paths, tuple(specs)


def output_status(paths: LocalPreflightPaths, value: StaticPreflightRequest):
    return validate_output_destinations(
        paths,
        value,
        process_run_ids=(),
        disk_usage_provider=lambda _path: SimpleNamespace(free=4096),
    )


def test_request_is_strict_deterministic_and_path_free() -> None:
    value = request()
    assert StaticPreflightRequest.from_mapping(value.as_dict()) == value
    assert value.request_fingerprint == request().request_fingerprint
    assert "C:\\" not in str(value.as_dict())
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_PREFLIGHT_INVALID$"
    ):
        StaticPreflightRequest.from_mapping({**value.as_dict(), "unknown": True})


@pytest.mark.parametrize(
    ("command", "result", "code"),
    [
        (
            "status --porcelain=v1 --untracked-files=all",
            " M file.py",
            "EOS_DIAG_REPOSITORY_STATE_INVALID",
        ),
        (
            "status --porcelain=v1 --untracked-files=all",
            "?? new.py",
            "EOS_DIAG_REPOSITORY_STATE_INVALID",
        ),
        ("branch --show-current", "", "EOS_DIAG_REPOSITORY_STATE_INVALID"),
        ("branch --show-current", "main", "EOS_DIAG_REPOSITORY_STATE_INVALID"),
        (
            "remote get-url origin",
            "https://github.com/example/wrong.git",
            "EOS_DIAG_REPOSITORY_STATE_INVALID",
        ),
        ("rev-parse HEAD", "2" * 40, "EOS_DIAG_SOURCE_COMMIT_MISMATCH"),
        (
            "rev-parse origin/develop",
            "3" * 40,
            "EOS_DIAG_SOURCE_COMMIT_MISMATCH",
        ),
    ],
)
def test_repository_rejects_dirty_detached_wrong_identity(
    tmp_path: Path, command: str, result: str, code: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    with pytest.raises(EOSDiagnosticPreflightError, match=f"^{code}$"):
        validate_repository_state(
            root, request(), command_runner=git_runner(**{command: result})
        )


def test_repository_valid_and_merge_in_progress(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".git").mkdir()
    assert (
        validate_repository_state(root, request(), command_runner=git_runner()).status
        == "passed"
    )
    (root / ".git" / "MERGE_HEAD").touch()
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_REPOSITORY_STATE_INVALID$"
    ):
        validate_repository_state(root, request(), command_runner=git_runner())


def test_backend_explicit_modules_are_deterministic_and_reject_duplicates(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "src" / "backend.py").write_text("VALUE = 1\n", encoding="utf-8")
    modules = (BackendModuleSpec("backend", "src/backend.py"),)
    first = build_backend_identity(root, source_commit=SHA, modules=modules)
    second = build_backend_identity(root, source_commit=SHA, modules=modules)
    assert first.backend_fingerprint == second.backend_fingerprint
    assert all(not Path(name).is_absolute() for name in dict(first.module_fingerprints))
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_BACKEND_FINGERPRINT_INVALID$"
    ):
        build_backend_identity(root, source_commit=SHA, modules=modules * 2)
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_BACKEND_FINGERPRINT_INVALID$"
    ):
        build_backend_identity(
            root,
            source_commit=SHA,
            modules=(BackendModuleSpec("bad", "../outside.py"),),
        )


def test_backend_rejects_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "backend.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    link = root / "link.py"
    link.write_text("synthetic link target", encoding="utf-8")
    original = Path.is_symlink
    monkeypatch.setattr(Path, "is_symlink", lambda path: path == link or original(path))
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_BACKEND_FINGERPRINT_INVALID$"
    ):
        build_backend_identity(
            root, source_commit=SHA, modules=(BackendModuleSpec("link", "link.py"),)
        )


def test_backend_detects_file_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    source = root / "backend.py"
    source.write_text("VALUE = 1\n", encoding="utf-8")
    original = Path.read_bytes

    def mutating_read(path: Path) -> bytes:
        payload = original(path)
        if path == source:
            path.write_bytes(payload + b"# drift\n")
        return payload

    monkeypatch.setattr(Path, "read_bytes", mutating_read)
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_BACKEND_FINGERPRINT_INVALID$"
    ):
        build_backend_identity(
            root,
            source_commit=SHA,
            modules=(BackendModuleSpec("backend", "backend.py"),),
        )


def test_dependency_snapshot_is_deterministic_strict_and_path_free() -> None:
    requirements = (DependencyRequirement("torch"), DependencyRequirement("PyYAML"))
    versions = {"torch": "2.7.1+cu128", "PyYAML": "6.0.2"}
    build = lambda items=requirements: build_dependency_identity(
        items,
        python_version="3.12.1",
        platform_identity="win32-AMD64",
        torch_version="2.7.1+cu128",
        cuda_build="12.8",
        cudnn_version="9.7",
        version_provider=versions.__getitem__,
    )
    assert (
        build().dependency_fingerprint
        == build(tuple(reversed(requirements))).dependency_fingerprint
    )
    assert "site-packages" not in str(build().as_dict())
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID$"
    ):
        build(requirements + (DependencyRequirement("torch"),))
    versions["torch"] = "missing"
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_DEPENDENCY_SNAPSHOT_INVALID$"
    ):
        build()


def test_input_roots_use_metadata_only_without_payload_reads(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _paths, specs = make_paths(tmp_path)
    monkeypatch.setattr(Path, "read_bytes", lambda _path: pytest.fail("payload read"))
    statuses = validate_input_roots(specs)
    assert all(item.payload_reads == item.write_attempts == 0 for item in statuses)


def test_input_roots_reject_missing_manifest_overlap_and_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    paths, specs = make_paths(tmp_path)
    (paths.prompt_root / "prompt-manifest.json").unlink()
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_INPUT_ROOT_INVALID$"
    ):
        validate_input_roots(specs)
    (paths.prompt_root / "prompt-manifest.json").touch()
    overlap = replace(
        specs[2],
        path=paths.tokenizer_root,
        expected_metadata_name="tokenizer-manifest.json",
    )
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_INPUT_ROOT_INVALID$"
    ):
        validate_input_roots((*specs[:2], overlap))
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda path: path == paths.checkpoint_root or original(path),
    )
    with pytest.raises(
        EOSDiagnosticPreflightError, match="^EOS_DIAG_INPUT_ROOT_INVALID$"
    ):
        validate_input_roots(specs)


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        ("exists", "EOS_DIAG_OUTPUT_CONFLICT"),
        ("same", "EOS_DIAG_OUTPUT_CONFLICT"),
        ("source", "EOS_DIAG_OUTPUT_ROOT_INVALID"),
        ("input", "EOS_DIAG_OUTPUT_ROOT_INVALID"),
        ("disk", "EOS_DIAG_DISK_SPACE_INSUFFICIENT"),
        ("length", "EOS_DIAG_PATH_LENGTH_EXCEEDED"),
        ("lock", "EOS_DIAG_LOCK_CONFLICT"),
        ("process", "EOS_DIAG_PROCESS_CONFLICT"),
        ("reserved", "EOS_DIAG_OUTPUT_CONFLICT"),
        ("symlink_parent", "EOS_DIAG_OUTPUT_ROOT_INVALID"),
    ],
)
def test_output_preflight_blocks_conflicts(
    tmp_path: Path,
    mutation: str,
    code: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    paths, _specs = make_paths(tmp_path)
    value = request(maximum_path_length=512)
    process_ids: tuple[str, ...] = ()
    disk = 4096
    if mutation == "exists":
        paths.output_root.mkdir()
    elif mutation == "same":
        paths = replace(paths, staging_root=paths.output_root)
    elif mutation == "source":
        paths = replace(paths, output_root=paths.repository_root / "output")
    elif mutation == "input":
        paths = replace(paths, output_root=paths.checkpoint_root / "output")
    elif mutation == "disk":
        disk = 1
    elif mutation == "length":
        value = request(maximum_path_length=20)
    elif mutation == "lock":
        paths.lock_path.touch()
    elif mutation == "reserved":
        paths = replace(paths, output_root=paths.output_root.with_name("CON"))
    elif mutation == "symlink_parent":
        parent = paths.output_root.parent
        original = Path.is_symlink
        monkeypatch.setattr(
            Path, "is_symlink", lambda path: path == parent or original(path)
        )
    else:
        process_ids = (RUN_ID,)
    with pytest.raises(EOSDiagnosticPreflightError, match=f"^{code}$"):
        validate_output_destinations(
            paths,
            value,
            process_run_ids=process_ids,
            disk_usage_provider=lambda _path: SimpleNamespace(free=disk),
        )


def test_synthetic_complete_preflight_passes_but_execution_stays_false(
    tmp_path: Path,
) -> None:
    paths, specs = make_paths(tmp_path)
    cp, tok, prm, back, dep, mat = (
        checkpoint(),
        tokenizer(),
        prompt(),
        backend(),
        dependency(),
        matrix(),
    )
    req = request(cp, tok, prm, back, dep, mat)
    result = run_static_preflight(
        req,
        paths=paths,
        repository_state=validate_repository_state(
            paths.repository_root, req, command_runner=git_runner()
        ),
        backend=back,
        dependency=dep,
        checkpoint=cp,
        tokenizer=tok,
        prompt_set=prm,
        binding=binding(cp, tok, prm),
        matrix=mat,
        input_statuses=validate_input_roots(specs),
        output_status=output_status(paths, req),
    )
    assert result.status == "passed"
    assert result.gate_1_status == result.gate_2_status == "passed"
    assert result.diagnostic_execution_allowed is False
    assert len(EXACT_ARTIFACT_FILENAMES) == 18
    assert req.expected_artifact_set_fingerprint == diagnostic_fingerprint(
        list(EXACT_ARTIFACT_FILENAMES)
    )


def test_incomplete_prompt_and_backend_dependency_block_gates(tmp_path: Path) -> None:
    paths, specs = make_paths(tmp_path)
    cp, tok = checkpoint(), tokenizer()
    complete_prompt = prompt()
    incomplete_prompt = prompt(prompt_set_id=None)
    incomplete_backend = backend(module_fingerprints=None)
    incomplete_dependency = dependency(dependency_entries=None)
    mat = matrix()
    req = request(
        cp, tok, incomplete_prompt, incomplete_backend, incomplete_dependency, mat
    )
    result = run_static_preflight(
        req,
        paths=paths,
        repository_state=validate_repository_state(
            paths.repository_root, req, command_runner=git_runner()
        ),
        backend=incomplete_backend,
        dependency=incomplete_dependency,
        checkpoint=cp,
        tokenizer=tok,
        prompt_set=incomplete_prompt,
        binding=binding(cp, tok, complete_prompt),
        matrix=mat,
        input_statuses=validate_input_roots(specs),
        output_status=output_status(paths, req),
    )
    assert result.status == "blocked"
    assert result.gate_1_status == result.gate_2_status == "blocked"
    assert {item["blocking_gate"] for item in result.blockers} == {
        "EOS-DIAG-1",
        "EOS-DIAG-2",
    }


def test_preflight_section_passes_r1_plan_schema_without_fake_completion(
    tmp_path: Path,
) -> None:
    paths, specs = make_paths(tmp_path)
    cp, tok, prm, back, dep, mat = (
        checkpoint(),
        tokenizer(),
        prompt(),
        backend(),
        dependency(),
        matrix(),
    )
    req = request(cp, tok, prm, back, dep, mat)
    result = run_static_preflight(
        req,
        paths=paths,
        repository_state=validate_repository_state(
            paths.repository_root, req, command_runner=git_runner()
        ),
        backend=back,
        dependency=dep,
        checkpoint=cp,
        tokenizer=tok,
        prompt_set=prm,
        binding=binding(cp, tok, prm),
        matrix=mat,
        input_statuses=validate_input_roots(specs),
        output_status=output_status(paths, req),
    )
    artifact = new_diagnostic_artifact(
        artifact_type="diagnostic_run_manifest",
        diagnostic_run_id=RUN_ID,
        checkpoint_identity_fingerprint=cp.identity_fingerprint,
        tokenizer_identity_fingerprint=tok.identity_fingerprint,
        prompt_set_fingerprint=prm.identity_fingerprint,
        generation_matrix_fingerprint=mat.matrix_fingerprint,
        source_commit=SHA,
        created_at="2099-01-01T00:00:00Z",
        record_count=1,
        payload={
            "purpose": "Synthetic R3 metadata-only preflight rehearsal",
            "execution_mode": "synthetic_schema_rehearsal",
            "permissions": {
                "checkpoint_load": False,
                "tokenizer_load": False,
                "gpu": False,
                "generation": False,
                "checkpoint_write": False,
                "training": False,
            },
            "exact_artifact_set": list(EXACT_ARTIFACT_FILENAMES),
            "predecessor_diagnostic_run_id": None,
            "preflight": build_diagnostic_plan_preflight_section(result),
        },
    )
    assert artifact.payload["preflight"]["diagnostic_execution_allowed"] is False
    assert not (tmp_path / "completion-evidence.json").exists()
    tampered = build_diagnostic_plan_preflight_section(result)
    tampered["preflight_fingerprint"] = FP("f")
    with pytest.raises(
        EOSDiagnosticArtifactError,
        match="^EOS_DIAGNOSTIC_ARTIFACT_INTEGRITY_MISMATCH$",
    ):
        new_diagnostic_artifact(
            artifact_type="diagnostic_run_manifest",
            diagnostic_run_id=RUN_ID,
            checkpoint_identity_fingerprint=cp.identity_fingerprint,
            tokenizer_identity_fingerprint=tok.identity_fingerprint,
            prompt_set_fingerprint=prm.identity_fingerprint,
            generation_matrix_fingerprint=mat.matrix_fingerprint,
            source_commit=SHA,
            created_at="2099-01-01T00:00:00Z",
            record_count=1,
            payload={
                **dict(artifact.payload),
                "preflight": tampered,
            },
        )
