"""
Analyzer plugin discovery.

Scans analyzers/ subpackages and top-level modules for BaseAnalyzer subclasses.
Adding a new analyzer requires no pipeline edits.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from typing import Type

from webvac.analyzers.base import BaseAnalyzer


def discover_analyzers(
    package_name: str = "webvac.analyzers",
    *,
    enabled_only: dict[str, bool] | None = None,
) -> list[BaseAnalyzer]:
    """
    Load and instantiate every BaseAnalyzer subclass found under analyzers/.

    Subpackages (e.g. analyzers/headers/analyzer.py) are scanned automatically.
    """
    found: list[Type[BaseAnalyzer]] = []
    seen_names: set[str] = set()

    package = importlib.import_module(package_name)

    def _register(cls: Type[BaseAnalyzer]) -> None:
        if cls is BaseAnalyzer or cls.__name__ == "BaseAnalyzer":
            return
        if not inspect.isclass(cls) or not issubclass(cls, BaseAnalyzer):
            return
        if inspect.isabstract(cls):
            return
        if cls.name in seen_names:
            return
        seen_names.add(cls.name)
        found.append(cls)

    # Top-level modules in analyzers/
    if hasattr(package, "__path__"):
        for _importer, mod_name, ispkg in pkgutil.iter_modules(
            package.__path__, package.__name__ + "."
        ):
            if mod_name.endswith(".base") or mod_name.endswith(".context"):
                continue
            if mod_name.endswith(".plugins") or mod_name.endswith(".engine"):
                continue
            try:
                module = importlib.import_module(mod_name)
            except ImportError:
                continue
            for _, obj in inspect.getmembers(module, inspect.isclass):
                if obj.__module__ == module.__name__:
                    _register(obj)
            # Subpackage pattern: analyzers/headers/analyzer.py
            if ispkg:
                analyzer_mod = f"{mod_name}.analyzer"
                try:
                    sub = importlib.import_module(analyzer_mod)
                    for _, obj in inspect.getmembers(sub, inspect.isclass):
                        if obj.__module__ == sub.__name__:
                            _register(obj)
                except ImportError:
                    pass

    instances: list[BaseAnalyzer] = []
    for cls in found:
        if enabled_only is not None and not enabled_only.get(cls.name, True):
            continue
        instances.append(cls())
    return sorted(instances, key=lambda a: a.name)
