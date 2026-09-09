"""The isolation registry (assumption B3).

Hand-written per-module isolation tests decay the moment someone is in a hurry.
A registry that fails on omission cannot be forgotten: `tests/test_registry_
completeness.py` enumerates every concrete `TenantScopedModel` and fails if one
is not registered here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class RegisteredModel:
    model: type
    factory: Callable
    #: Endpoints that expose this model, for the role-boundary family.
    endpoints: tuple = field(default_factory=tuple)
    #: Models deliberately excluded from API exposure (still isolation-tested).
    api_exposed: bool = True


_REGISTRY: dict[str, RegisteredModel] = {}


def register(model, factory, endpoints=(), api_exposed=True):
    key = f"{model._meta.app_label}.{model.__name__}"
    _REGISTRY[key] = RegisteredModel(
        model=model, factory=factory, endpoints=tuple(endpoints),
        api_exposed=api_exposed,
    )
    return model


def registered():
    return dict(_REGISTRY)


def registered_models():
    return [entry.model for entry in _REGISTRY.values()]
