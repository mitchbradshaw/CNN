"""
registry.py
============
The adapter registry: a name -> AdapterSpec map, populated by each adapter
module registering itself on import (see any `Adapters/<stage>_<algo>.py`
for the pattern). `discover_adapters()` imports every adapter module in
this package so callers don't need to know the full list up front.
"""

import importlib
import pkgutil
import sys
import traceback

_REGISTRY = {}


def register(spec):
    """Register an AdapterSpec. Called once, at module import time, by
    each adapter file. Raises if the name is already taken (a copy-paste
    duplicate name, most likely)."""
    if spec.name in _REGISTRY:
        raise ValueError(f"Adapter '{spec.name}' is already registered.")
    _REGISTRY[spec.name] = spec
    return spec


def get_adapter(name):
    if name not in _REGISTRY:
        raise KeyError(f"Unknown adapter '{name}'. Available: {sorted(_REGISTRY)}")
    return _REGISTRY[name]


def list_adapters(stage=None):
    """All registered adapters, optionally filtered to one stage, sorted
    by name for a stable UI listing order."""
    specs = _REGISTRY.values()
    if stage is not None:
        specs = [s for s in specs if s.stage == stage]
    return sorted(specs, key=lambda s: s.name)


def discover_adapters():
    """Import every adapter module in `Adapters/` so it self-registers.
    Safe to call more than once (re-importing an already-imported module
    is a no-op). Call this once before using `get_adapter`/`list_adapters`
    if you haven't explicitly imported the adapter module you need.

    A module that fails to import (e.g. an optional third-party dependency
    is missing or broken, like kymatio vs. a newer scipy) is skipped with a
    warning rather than taking down every other adapter — one broken
    dependency shouldn't block the 15 adapters that don't need it.
    """
    import Adapters
    for _, modname, _ in pkgutil.iter_modules(Adapters.__path__):
        if modname in ("base", "registry"):
            continue
        try:
            importlib.import_module(f"Adapters.{modname}")
        except Exception:
            print(f"[Adapters.registry] Skipping 'Adapters.{modname}' — failed to import:",
                  file=sys.stderr)
            traceback.print_exc(file=sys.stderr)
    return list_adapters()
