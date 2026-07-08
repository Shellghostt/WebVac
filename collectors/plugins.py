"""Collector plugin discovery."""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Type

from collectors.base import BaseCollector


def discover_collectors(
    package_name: str = "collectors",
    *,
    enabled_only: dict[str, bool] | None = None,
) -> list[BaseCollector]:
    found: list[Type[BaseCollector]] = []
    seen: set[str] = set()

    package = importlib.import_module(package_name)

    def _register(cls: Type[BaseCollector]) -> None:
        if cls is BaseCollector:
            return
        if not inspect.isclass(cls) or not issubclass(cls, BaseCollector):
            return
        if inspect.isabstract(cls):
            return
        if cls.name in seen:
            return
        seen.add(cls.name)
        found.append(cls)

    if hasattr(package, "__path__"):
        for _importer, mod_name, ispkg in pkgutil.iter_modules(
            package.__path__, package.__name__ + "."
        ):
            skip_suffixes = (".base", ".context", ".plugins", ".engine")
            if any(mod_name.endswith(s) for s in skip_suffixes):
                continue
            if ispkg:
                try:
                    sub = importlib.import_module(f"{mod_name}.collector")
                    for _, obj in inspect.getmembers(sub, inspect.isclass):
                        if obj.__module__ == sub.__name__:
                            _register(obj)
                except ImportError:
                    pass

    instances = []
    for cls in found:
        if enabled_only is not None and not enabled_only.get(cls.name, True):
            continue
        instances.append(cls())
    return sorted(instances, key=lambda c: c.name)
