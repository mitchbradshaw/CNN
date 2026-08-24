"""
recipes.py
===========
The recipe is the single identifier tying together reproducibility,
artifact naming, cache lookup, and "what have I already tried" — one
mechanism serving all four, never special-cased per use.

    recipe = {
        "recording_id": <int>,
        "span": [start_idx, end_idx] | None,   # None = whole channel
        "steps": [ {"stage": ..., "algorithm": ..., "params": {...}}, ... ]
    }

`stage` is one of `STAGES` below. `steps` is ORDERED and may chain (e.g.
preprocessing -> preprocessing -> detection) — each step's output feeds the
next (see `Working.execution.execute_recipe`).

Hashing
-------
`recipe_hash()` serialises with canonical JSON (sorted keys, no whitespace
variation, numpy scalars coerced to native Python types before
serialisation) then SHA-256, keeping the first 8 hex chars as the short
hash used everywhere else (filenames, `encodings`/`configs` lookups).
Identical recipes produce identical hashes regardless of dict key order,
whether a parameter was written as a Python float or a numpy float64 of the
same value, and across machines/sessions — Python's json encoder formats
floats via `repr()`, which is a deterministic, shortest-round-trip
representation of the underlying IEEE-754 double on any CPython 3.x.

No ORM, no UI imports — callable from a bare script exactly like
`Working.database`.
"""

import hashlib
import json

STAGES = ("preprocessing", "detection", "catalogue", "comparison")


def _normalize(obj):
    """Recursively coerce numpy scalar types to native Python int/float/bool
    so `np.float64(0.05)` and the plain literal `0.05` serialise identically.
    Raises on numpy arrays and other non-JSON-safe types rather than
    guessing how to flatten them into a recipe.
    """
    # Imported lazily so this module has no hard numpy dependency for the
    # (common) case of a pure-Python recipe.
    try:
        import numpy as np
    except ImportError:
        np = None

    if np is not None:
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.bool_):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            raise TypeError(
                "Recipe params must be JSON-safe scalars/lists/dicts, not "
                "numpy arrays — pass e.g. arr.tolist() instead."
            )

    if isinstance(obj, dict):
        # A library_exemplar side-input binding hashes by what it *is*
        # (source file, channel, sample range), not by its local database
        # row id — the entry_id travels alongside as a convenience pointer
        # but is excluded here so it never enters canonical_json/recipe_hash
        # (ticket 14).
        if obj.get("source_kind") == "library_exemplar" and "entry_id" in obj:
            obj = {k: v for k, v in obj.items() if k != "entry_id"}
        return {str(k): _normalize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_normalize(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    raise TypeError(f"Recipe contains a non-JSON-safe value of type {type(obj)}: {obj!r}")


def canonical_json(recipe):
    """Canonical JSON string for `recipe`: sorted keys, no whitespace
    variation, numpy scalars normalised. Two recipes that are semantically
    identical always produce the same string, regardless of key insertion
    order or numpy-vs-native numeric types.
    """
    normalized = _normalize(recipe)
    return json.dumps(normalized, sort_keys=True, separators=(",", ":"))


def recipe_hash(recipe):
    """Full SHA-256 hex digest of `canonical_json(recipe)`."""
    canonical = canonical_json(recipe)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def short_hash(recipe):
    """First 8 hex chars of `recipe_hash` — the identifier used in
    filenames, the encoding cache, and the `configs`/`encodings` tables."""
    return recipe_hash(recipe)[:8]


def _normalize_side_inputs(side_inputs, step_index, source_kinds):
    """Validate and normalise one step's `side_inputs` map (name -> binding).

    Each binding names its `source_kind` (one of `source_kinds`) and the
    content that identifies it:
    - `root_signal`: no further content.
    - `earlier_step`: `step_index` of an earlier step in the same recipe
      (strictly less than this step's own position).
    - `library_exemplar`: `entry_id` (a convenience pointer, stripped from
      canonical_json by `_normalize`), `source_file`, `channel`, `start_idx`,
      `end_idx` — the content that constitutes the binding's actual
      identity.
    """
    if not side_inputs:
        return {}

    normalized = {}
    for name, binding in side_inputs.items():
        if not isinstance(binding, dict):
            raise ValueError(f"Step {step_index}: side_input {name!r} must be a dict.")
        source_kind = binding.get("source_kind")
        if source_kind not in source_kinds:
            raise ValueError(
                f"Step {step_index}: side_input {name!r} has unknown source_kind "
                f"{source_kind!r}; must be one of {source_kinds}."
            )

        if source_kind == "root_signal":
            normalized[name] = {"source_kind": "root_signal"}

        elif source_kind == "earlier_step":
            ref = binding.get("step_index")
            if not isinstance(ref, int) or not (0 <= ref < step_index):
                raise ValueError(
                    f"Step {step_index}: side_input {name!r} earlier_step "
                    f"step_index must name an earlier step in this recipe "
                    f"(0 <= step_index < {step_index}), got {ref!r}."
                )
            normalized[name] = {"source_kind": "earlier_step", "step_index": int(ref)}

        elif source_kind == "library_exemplar":
            required = ("entry_id", "source_file", "channel", "start_idx", "end_idx")
            missing = [k for k in required if binding.get(k) is None]
            if missing:
                raise ValueError(
                    f"Step {step_index}: side_input {name!r} library_exemplar "
                    f"binding is missing {missing}."
                )
            start_idx, end_idx = int(binding["start_idx"]), int(binding["end_idx"])
            if end_idx <= start_idx:
                raise ValueError(
                    f"Step {step_index}: side_input {name!r} library_exemplar "
                    f"end_idx must be > start_idx, got ({start_idx}, {end_idx})."
                )
            normalized[name] = {
                "source_kind": "library_exemplar",
                "entry_id": int(binding["entry_id"]),
                "source_file": str(binding["source_file"]),
                "channel": int(binding["channel"]),
                "start_idx": start_idx,
                "end_idx": end_idx,
            }

    return normalized


def make_recipe(recording_id, steps, span=None):
    """Build a well-formed recipe dict, validating stage names and
    normalising `span` to a plain [start, end] list (or None).

    Parameters
    ----------
    recording_id : int
    steps : list[dict]
        Each dict needs "stage" (one of `STAGES`), "algorithm" (str), and
        optionally "params" (dict, defaults to {}).
    span : (int, int), optional
        None means the whole channel.
    """
    if not steps:
        raise ValueError("A recipe needs at least one step.")

    # Lazily imported: SOURCE_KINDS lives in the adapter contract, a real
    # dependency only callers binding side-inputs need to pay for.
    from Adapters.base import SOURCE_KINDS

    norm_steps = []
    for i, step in enumerate(steps):
        stage = step.get("stage")
        if stage not in STAGES:
            raise ValueError(
                f"Step {i}: stage must be one of {STAGES}, got {stage!r}"
            )
        algorithm = step.get("algorithm")
        if not algorithm or not isinstance(algorithm, str):
            raise ValueError(f"Step {i}: 'algorithm' must be a non-empty string.")
        norm_steps.append({
            "stage": stage,
            "algorithm": algorithm,
            "params": dict(step.get("params") or {}),
            "side_inputs": _normalize_side_inputs(step.get("side_inputs"), i, SOURCE_KINDS),
        })

    norm_span = None
    if span is not None:
        start, end = span
        norm_span = [int(start), int(end)]
        if norm_span[1] <= norm_span[0]:
            raise ValueError(f"span end must be > start, got {norm_span}")

    # Lazily imported: chain validation pulls in the adapter registry
    # (Adapters/), a real dependency only `make_recipe` callers that build
    # actual chains need — a bare hash/serialisation use of this module
    # shouldn't have to pay for it at import time.
    from Working.chain_validation import validate_recipe_steps
    ok, reason = validate_recipe_steps(norm_steps)
    if not ok:
        raise ValueError(f"Invalid chain: {reason}")

    return {
        "recording_id": int(recording_id),
        "span": norm_span,
        "steps": norm_steps,
    }


def recipe_summary(recipe):
    """Short human-readable summary, e.g. 'prep.lowpass -> detection.rupture'
    — used in the run-history browser and status messages."""
    return " -> ".join(f"{s['stage']}.{s['algorithm']}" for s in recipe["steps"])
