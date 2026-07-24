"""Parameter counting that excludes repeated references to tied weights."""

from __future__ import annotations

from dataclasses import dataclass

from torch import nn

from .config import ModelConfig


@dataclass(frozen=True)
class ParameterCount:
    total: int
    trainable: int
    by_module: dict[str, int]
    tied_references_excluded: int


class ParameterCounter:
    """Count each distinct ``Parameter`` object exactly once."""

    @staticmethod
    def count(module: nn.Module) -> ParameterCount:
        if not isinstance(module, nn.Module):
            raise TypeError("module must be a torch.nn.Module")
        seen: set[int] = set()
        total = 0
        trainable = 0
        tied_references_excluded = 0
        by_module: dict[str, int] = {}
        for module_name, child in module.named_modules():
            own_count = 0
            for _, parameter in child.named_parameters(recurse=False):
                identity = id(parameter)
                if identity in seen:
                    tied_references_excluded += parameter.numel()
                    continue
                seen.add(identity)
                count = parameter.numel()
                own_count += count
                total += count
                if parameter.requires_grad:
                    trainable += count
            if own_count:
                by_module[module_name or "<root>"] = own_count
        return ParameterCount(total, trainable, by_module, tied_references_excluded)

    @staticmethod
    def expected_tiny_total(config: ModelConfig) -> int:
        embedding = config.vocab_size * config.hidden_size
        position = config.context_length * config.hidden_size
        block = (
            4 * config.hidden_size * config.hidden_size
            + 2 * config.hidden_size * config.ffn_size
            + config.ffn_size
            + 9 * config.hidden_size
        )
        final_norm = 2 * config.hidden_size
        return embedding + position + config.num_layers * block + final_norm
