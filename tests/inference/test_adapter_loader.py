from __future__ import annotations

import hashlib
import json
from dataclasses import FrozenInstanceError, replace
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

import src.inference.adapter_loader as loader
from src.inference.adapter_loader import (
    AdapterLoaderError,
    RuntimeDependencies,
    load_peft_adapter_runtime,
    tokenizer_fingerprint,
    unload_peft_adapter_runtime,
)
from src.inference.adapter_manifest import (
    AdapterManifest,
    ArtifactReference,
    ChatTemplateReference,
    GenerationConfigReference,
    TrainingRunReference,
)
from src.inference.adapter_validation import (
    AdapterConfigSummary,
    AdapterMetadataSummary,
    AdapterValidationResult,
    AdapterWeightsSummary,
    GenerationConfigSummary,
    ManifestIdentity,
    ValidatedArtifactIdentity,
)
from src.inference.model_loader import (
    BASE_QWEN_MODEL_ID,
    BASE_QWEN_REVISION,
)


PEFT_VERSION = "0.17.0"
TRANSFORMERS_VERSION = "4.57.6"
TORCH_VERSION = "2.7.1+cu118"
CHAT_TEMPLATE = "{% for message in messages %}{{ message.content }}{% endfor %}"


class FakeParameter:
    def __init__(
        self,
        *,
        requires_grad: bool = False,
        device: str = "cuda",
        dtype: str = "torch.bfloat16",
        freeze: bool = True,
    ) -> None:
        self.requires_grad = requires_grad
        self.device = SimpleNamespace(type=device)
        self.dtype = dtype
        self.freeze = freeze

    def requires_grad_(self, value: bool) -> FakeParameter:
        if self.freeze:
            self.requires_grad = value
        return self


class FakeModel:
    def __init__(
        self,
        *,
        adapter_name: str | None = None,
        no_adapter_parameters: bool = False,
        stubborn_trainable: bool = False,
        active_adapter: str | None = None,
        device: str = "cuda",
    ) -> None:
        self.training = True
        self.config = SimpleNamespace(use_cache=False)
        self.hf_device_map = {"": 0}
        self.gradient_checkpointing_disabled = False
        self._parameters = [("base.weight", FakeParameter(device=device))]
        if adapter_name is not None:
            if not no_adapter_parameters:
                self._parameters.append(
                    (
                        f"lora_A.{adapter_name}.weight",
                        FakeParameter(
                            requires_grad=stubborn_trainable,
                            device=device,
                            freeze=not stubborn_trainable,
                        ),
                    )
                )
            self.peft_config = {
                adapter_name: SimpleNamespace(
                    base_model_name_or_path=BASE_QWEN_MODEL_ID,
                    revision=BASE_QWEN_REVISION,
                )
            }
            self.active_adapters = [active_adapter or adapter_name]

    def eval(self) -> FakeModel:
        self.training = False
        return self

    def parameters(self) -> list[FakeParameter]:
        return [parameter for _, parameter in self._parameters]

    def named_parameters(self) -> list[tuple[str, FakeParameter]]:
        return list(self._parameters)

    def gradient_checkpointing_disable(self) -> None:
        self.gradient_checkpointing_disabled = True


class FakeCuda:
    def __init__(self) -> None:
        self.empty_calls = 0
        self.ipc_calls = 0
        self.fail_cleanup = False

    @staticmethod
    def is_available() -> bool:
        return True

    @staticmethod
    def get_device_name(_device: int) -> str:
        return "NVIDIA GeForce RTX 3060 Ti"

    @staticmethod
    def mem_get_info(_device: int) -> tuple[int, int]:
        return 6 * 1024**3, 8 * 1024**3

    @staticmethod
    def synchronize(_device: int) -> None:
        return None

    def empty_cache(self) -> None:
        self.empty_calls += 1
        if self.fail_cleanup:
            raise RuntimeError("synthetic cleanup failure")

    def ipc_collect(self) -> None:
        self.ipc_calls += 1


def make_snapshot(root: Path) -> Path:
    snapshot = root / BASE_QWEN_REVISION
    snapshot.mkdir()
    values: dict[str, bytes] = {
        "config.json": json.dumps(
            {"_name_or_path": BASE_QWEN_MODEL_ID, "model_type": "qwen2"}
        ).encode(),
        "generation_config.json": b"{}",
        "merges.txt": b"# synthetic-not-for-runtime\n",
        "tokenizer.json": b"{}",
        "tokenizer_config.json": json.dumps({"chat_template": CHAT_TEMPLATE}).encode(),
        "vocab.json": b"{}",
        "model.safetensors": b"synthetic-not-a-real-model",
    }
    for name, payload in values.items():
        (snapshot / name).write_bytes(payload)
    return snapshot


def make_manifest(root: Path, snapshot: Path) -> AdapterManifest:
    adapter_root = root / "synthetic-adapter-not-for-runtime"
    adapter_root.mkdir()
    manifest_path = adapter_root / "adapter-manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    checksum = "a" * 64
    return AdapterManifest(
        schema_version=1,
        adapter_name="synthetic-adapter-not-for-runtime",
        adapter_version="0.0.0-synthetic",
        base_model=BASE_QWEN_MODEL_ID,
        base_revision=BASE_QWEN_REVISION,
        tokenizer=BASE_QWEN_MODEL_ID,
        tokenizer_hash=tokenizer_fingerprint(snapshot),
        chat_template=ChatTemplateReference(
            "tokenizer_config.json#chat_template",
            hashlib.sha256(CHAT_TEMPLATE.encode()).hexdigest(),
        ),
        peft_version=PEFT_VERSION,
        transformers_version=TRANSFORMERS_VERSION,
        torch_version=TORCH_VERSION,
        generation_config=GenerationConfigReference(
            "generation-config.json", "b" * 64, "api_bounds_only"
        ),
        evaluation_fingerprint="c" * 64,
        training_run=TrainingRunReference(
            "SYNTHETIC-NOT-FOR-RUNTIME", "training-result.yaml", "d" * 64
        ),
        created_at="2026-08-05T00:00:00Z",
        adapter_config=ArtifactReference("adapter_config.json", checksum),
        adapter_weights=ArtifactReference("adapter_model.safetensors", "e" * 64),
        metadata=ArtifactReference("adapter-metadata.json", "f" * 64),
        manifest_path=manifest_path.resolve(),
    )


def make_validation(manifest: AdapterManifest) -> AdapterValidationResult:
    identity = ManifestIdentity(
        manifest.schema_version,
        manifest.adapter_name,
        manifest.adapter_version,
        manifest.base_model,
        manifest.base_revision,
        manifest.tokenizer,
        manifest.tokenizer_hash,
        manifest.chat_template.source,
        manifest.chat_template.sha256,
        manifest.peft_version,
        manifest.transformers_version,
        manifest.torch_version,
        manifest.evaluation_fingerprint,
        manifest.training_run.id,
        manifest.created_at,
    )
    references = {
        "adapter_config": manifest.adapter_config,
        "adapter_weights": manifest.adapter_weights,
        "metadata": manifest.metadata,
        "generation_config": ArtifactReference(
            manifest.generation_config.path, manifest.generation_config.sha256
        ),
        "training_result": ArtifactReference(
            manifest.training_run.result_path, manifest.training_run.result_sha256
        ),
    }
    artifacts = tuple(
        ValidatedArtifactIdentity(name, reference.path, reference.sha256, 1)
        for name, reference in sorted(references.items())
    )
    return AdapterValidationResult(
        manifest=identity,
        artifacts=artifacts,
        adapter_config=AdapterConfigSummary(
            "LORA", "CAUSAL_LM", 16, 32.0, 0.05, ("q_proj",), "none", True
        ),
        weights=AdapterWeightsSummary(1, 8, 4, ("F32",)),
        metadata=AdapterMetadataSummary(1, "qlora", "1" * 64, "2" * 40),
        generation_config=GenerationConfigSummary(
            256,
            0.7,
            0.9,
            50,
            1.05,
            True,
            (151643, 151645),
            151643,
            "api_bounds_only",
        ),
        validation_fingerprint="sha256:" + "3" * 64,
        warnings=(),
        validated_at="2026-08-05T00:00:01Z",
    )


def make_dependencies(
    state: dict[str, Any],
    *,
    peft_version: str = PEFT_VERSION,
    tokenizer_eos: int = 151645,
    tokenizer_pad: int = 151643,
    chat_template: str = CHAT_TEMPLATE,
    base_failure: bool = False,
    peft_failure: bool = False,
    no_adapter_parameters: bool = False,
    stubborn_trainable: bool = False,
    active_adapter: str | None = None,
    device: str = "cuda",
) -> RuntimeDependencies:
    cuda = FakeCuda()
    torch_module = SimpleNamespace(
        __version__=TORCH_VERSION, bfloat16="torch.bfloat16", cuda=cuda
    )

    class AutoTokenizer:
        @staticmethod
        def from_pretrained(path: Path, **kwargs: Any) -> Any:
            state["tokenizer_call"] = (path, kwargs)
            return SimpleNamespace(
                eos_token_id=tokenizer_eos,
                pad_token_id=tokenizer_pad,
                chat_template=chat_template,
            )

    class AutoModel:
        @staticmethod
        def from_pretrained(path: Path, **kwargs: Any) -> FakeModel:
            state["base_call"] = (path, kwargs)
            if base_failure:
                raise RuntimeError("synthetic base failure")
            return FakeModel(device=device)

    class PeftModel:
        @staticmethod
        def from_pretrained(base: FakeModel, path: Path, **kwargs: Any) -> FakeModel:
            state["peft_call"] = (base, path, kwargs)
            if peft_failure:
                raise RuntimeError("synthetic peft failure")
            return FakeModel(
                adapter_name=kwargs["adapter_name"],
                no_adapter_parameters=no_adapter_parameters,
                stubborn_trainable=stubborn_trainable,
                active_adapter=active_adapter,
                device=device,
            )

    state["cuda"] = cuda
    return RuntimeDependencies(
        torch=torch_module,
        transformers=SimpleNamespace(__version__=TRANSFORMERS_VERSION),
        peft=SimpleNamespace(__version__=peft_version),
        auto_tokenizer=AutoTokenizer,
        auto_model=AutoModel,
        peft_model=PeftModel,
    )


@pytest.fixture
def runtime(
    tmp_path: Path,
) -> tuple[
    AdapterManifest, AdapterValidationResult, Path, dict[str, Any], RuntimeDependencies
]:
    snapshot = make_snapshot(tmp_path)
    manifest = make_manifest(tmp_path, snapshot)
    validation = make_validation(manifest)
    state: dict[str, Any] = {}
    dependencies = make_dependencies(state)
    return manifest, validation, snapshot, state, dependencies


def load_runtime(
    manifest: AdapterManifest,
    validation: AdapterValidationResult,
    snapshot: Path,
    dependencies: RuntimeDependencies,
):
    return load_peft_adapter_runtime(
        manifest=manifest,
        validation=validation,
        base_model_path=snapshot,
        adapter_root=manifest.manifest_root,
        dependencies=dependencies,
        artifact_validator=lambda _manifest: validation,
    )


def assert_error(code: str, function: Any) -> AdapterLoaderError:
    with pytest.raises(AdapterLoaderError) as captured:
        function()
    assert captured.value.code == code
    assert str(captured.value) == code
    assert "D:" not in captured.value.safe_message
    return captured.value


def test_loads_explicit_local_runtime_and_returns_safe_handle(runtime) -> None:
    manifest, validation, snapshot, state, dependencies = runtime
    handle = load_runtime(manifest, validation, snapshot, dependencies)

    assert handle.identity.adapter_name == manifest.adapter_name
    assert handle.identity.validation_fingerprint == validation.validation_fingerprint
    assert handle.identity.dependencies.peft == PEFT_VERSION
    assert handle.model.training is False
    assert handle.model.config.use_cache is True
    assert handle.model.gradient_checkpointing_disabled is True
    assert all(not parameter.requires_grad for parameter in handle.model.parameters())
    assert str(snapshot.resolve()) not in repr(handle)
    with pytest.raises(FrozenInstanceError):
        handle.identity.adapter_name = "changed"  # type: ignore[misc]

    tokenizer_options = state["tokenizer_call"][1]
    base_options = state["base_call"][1]
    peft_options = state["peft_call"][2]
    assert tokenizer_options == {
        "use_fast": True,
        "local_files_only": True,
        "trust_remote_code": False,
        "revision": BASE_QWEN_REVISION,
    }
    assert base_options["local_files_only"] is True
    assert base_options["trust_remote_code"] is False
    assert base_options["use_safetensors"] is True
    assert base_options["device_map"] == {"": 0}
    assert peft_options == {
        "adapter_name": manifest.adapter_name,
        "is_trainable": False,
        "local_files_only": True,
    }


def test_runtime_identity_is_deterministic_without_global_cache(runtime) -> None:
    manifest, validation, snapshot, _state, dependencies = runtime
    first = load_runtime(manifest, validation, snapshot, dependencies)
    second = load_runtime(manifest, validation, snapshot, dependencies)

    assert first is not second
    assert first.model is not second.model
    assert first.identity == second.identity


@pytest.mark.parametrize("field", ["manifest", "fingerprint", "artifact"])
def test_rejects_stale_or_mismatched_validation_result(runtime, field: str) -> None:
    manifest, validation, snapshot, _state, dependencies = runtime
    if field == "manifest":
        validation = replace(
            validation,
            manifest=replace(validation.manifest, adapter_version="different"),
        )
    elif field == "fingerprint":
        validation = replace(validation, validation_fingerprint="sha256:" + "9" * 64)
    else:
        validation = replace(
            validation,
            artifacts=(replace(validation.artifacts[0], sha256="9" * 64),)
            + validation.artifacts[1:],
        )
    original = make_validation(manifest)
    assert_error(
        "ADAPTER_VALIDATION_RESULT_INCOMPATIBLE",
        lambda: load_peft_adapter_runtime(
            manifest=manifest,
            validation=validation,
            base_model_path=snapshot,
            adapter_root=manifest.manifest_root,
            dependencies=dependencies,
            artifact_validator=lambda _manifest: original,
        ),
    )


def test_rejects_adapter_root_mismatch(runtime, tmp_path: Path) -> None:
    manifest, validation, snapshot, _state, dependencies = runtime
    other = tmp_path / "other"
    other.mkdir()
    assert_error(
        "ADAPTER_VALIDATION_RESULT_INCOMPATIBLE",
        lambda: load_peft_adapter_runtime(
            manifest=manifest,
            validation=validation,
            base_model_path=snapshot,
            adapter_root=other,
            dependencies=dependencies,
            artifact_validator=lambda _manifest: validation,
        ),
    )


def test_rejects_symlinked_base_snapshot(
    runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, validation, snapshot, _state, dependencies = runtime
    original = Path.is_symlink
    monkeypatch.setattr(
        Path,
        "is_symlink",
        lambda candidate: candidate == snapshot or original(candidate),
    )
    assert_error(
        "ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE",
        lambda: load_runtime(manifest, validation, snapshot, dependencies),
    )


def test_dependency_missing_is_structured(
    runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, validation, snapshot, _state, _dependencies = runtime
    monkeypatch.setattr(
        loader,
        "_load_dependencies",
        lambda: (_ for _ in ()).throw(
            AdapterLoaderError("ADAPTER_RUNTIME_DEPENDENCY_MISSING")
        ),
    )
    assert_error(
        "ADAPTER_RUNTIME_DEPENDENCY_MISSING",
        lambda: load_peft_adapter_runtime(
            manifest=manifest,
            validation=validation,
            base_model_path=snapshot,
            adapter_root=manifest.manifest_root,
            artifact_validator=lambda _manifest: validation,
        ),
    )


def test_dependency_versions_use_exact_match(runtime) -> None:
    manifest, validation, snapshot, state, _dependencies = runtime
    dependencies = make_dependencies(state, peft_version="0.17.1")
    assert_error(
        "ADAPTER_RUNTIME_VERSION_INCOMPATIBLE",
        lambda: load_runtime(manifest, validation, snapshot, dependencies),
    )
    assert "tokenizer_call" not in state


def test_rejects_unavailable_approved_cuda_before_model_load(runtime) -> None:
    manifest, validation, snapshot, state, dependencies = runtime
    state["cuda"].is_available = lambda: False
    assert_error(
        "ADAPTER_LOAD_FAILED",
        lambda: load_runtime(manifest, validation, snapshot, dependencies),
    )
    assert "tokenizer_call" not in state


@pytest.mark.parametrize("condition", ["missing", "revision", "identity"])
def test_rejects_invalid_base_snapshot(runtime, condition: str, tmp_path: Path) -> None:
    manifest, validation, snapshot, _state, dependencies = runtime
    if condition == "missing":
        snapshot = tmp_path / "missing"
        code = "ADAPTER_BASE_SNAPSHOT_NOT_FOUND"
    elif condition == "revision":
        renamed = tmp_path / ("9" * 40)
        snapshot.rename(renamed)
        snapshot = renamed
        code = "ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE"
    else:
        (snapshot / "config.json").write_text(
            json.dumps({"_name_or_path": "different/model", "model_type": "qwen2"}),
            encoding="utf-8",
        )
        code = "ADAPTER_BASE_SNAPSHOT_INCOMPATIBLE"
    assert_error(
        code, lambda: load_runtime(manifest, validation, snapshot, dependencies)
    )


@pytest.mark.parametrize("condition", ["hash", "eos", "pad"])
def test_rejects_tokenizer_identity_or_special_token_mismatch(
    runtime, condition: str
) -> None:
    manifest, validation, snapshot, state, _dependencies = runtime
    if condition == "hash":
        manifest = replace(manifest, tokenizer_hash="9" * 64)
        validation = replace(
            validation, manifest=replace(validation.manifest, tokenizer_hash="9" * 64)
        )
        dependencies = make_dependencies(state)
    elif condition == "eos":
        dependencies = make_dependencies(state, tokenizer_eos=1)
    else:
        dependencies = make_dependencies(state, tokenizer_pad=1)
    assert_error(
        "ADAPTER_TOKENIZER_INCOMPATIBLE",
        lambda: load_runtime(manifest, validation, snapshot, dependencies),
    )


def test_rejects_chat_template_mismatch(runtime) -> None:
    manifest, validation, snapshot, state, _dependencies = runtime
    dependencies = make_dependencies(state, chat_template="different")
    assert_error(
        "ADAPTER_CHAT_TEMPLATE_INCOMPATIBLE",
        lambda: load_runtime(manifest, validation, snapshot, dependencies),
    )


@pytest.mark.parametrize("stage", ["base", "peft"])
def test_load_failure_is_sanitized_and_cleans_partial_resources(
    runtime, stage: str
) -> None:
    manifest, validation, snapshot, state, _dependencies = runtime
    dependencies = make_dependencies(
        state, base_failure=stage == "base", peft_failure=stage == "peft"
    )
    assert_error(
        "ADAPTER_LOAD_FAILED",
        lambda: load_runtime(manifest, validation, snapshot, dependencies),
    )
    assert state["cuda"].empty_calls == 1


@pytest.mark.parametrize(
    "options",
    [
        {"no_adapter_parameters": True},
        {"stubborn_trainable": True},
        {"active_adapter": "different"},
        {"device": "cpu"},
    ],
)
def test_rejects_invalid_post_load_state(runtime, options: dict[str, Any]) -> None:
    manifest, validation, snapshot, state, _dependencies = runtime
    dependencies = make_dependencies(state, **options)
    assert_error(
        "ADAPTER_POST_LOAD_VALIDATION_FAILED",
        lambda: load_runtime(manifest, validation, snapshot, dependencies),
    )
    assert state["cuda"].empty_calls == 1


def test_cleanup_failure_does_not_replace_original_load_error(runtime) -> None:
    manifest, validation, snapshot, state, _dependencies = runtime
    dependencies = make_dependencies(state, peft_failure=True)
    state["cuda"].fail_cleanup = True
    assert_error(
        "ADAPTER_LOAD_FAILED",
        lambda: load_runtime(manifest, validation, snapshot, dependencies),
    )


def test_unload_is_explicit_and_idempotent(runtime) -> None:
    manifest, validation, snapshot, state, dependencies = runtime
    handle = load_runtime(manifest, validation, snapshot, dependencies)

    assert unload_peft_adapter_runtime(handle) is True
    assert handle.unloaded is True
    assert handle.model is None and handle.tokenizer is None and handle.torch is None
    assert state["cuda"].empty_calls == 1
    assert unload_peft_adapter_runtime(handle) is False
    assert state["cuda"].empty_calls == 1


def test_unload_failure_is_structured(runtime) -> None:
    manifest, validation, snapshot, state, dependencies = runtime
    handle = load_runtime(manifest, validation, snapshot, dependencies)
    state["cuda"].fail_cleanup = True
    assert_error("ADAPTER_UNLOAD_FAILED", lambda: unload_peft_adapter_runtime(handle))
    assert handle.unloaded is True
