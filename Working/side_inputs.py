"""
side_inputs.py
================
Turns a step's `side_inputs` binding map (see `Working.recipes.make_recipe`)
into the typed values its adapter's `run` actually needs. One function,
`resolve_side_inputs`, is the single seam `Working.execution.execute_recipe`
calls before running any step that declares side inputs — nothing else
resolves a binding.

A binding names a `source_kind` (`Adapters.base.SOURCE_KINDS`) and the
content that identifies it:
- `root_signal`: the chain's own root signal, already loaded.
- `earlier_step`: an earlier step's typed output, already computed this run
  (see `typed_step_value`, used by `execute_recipe` to build `step_results`).
- `library_exemplar`: a signal sliced fresh off disk from another recording
  by (source_file, channel, start_idx, end_idx) — content-addressed per
  ticket 14, resolved without needing a live `motif_entry` row so an
  exported recipe still resolves on another machine's database.
"""

import numpy as np

from Working.database import queries as q
from Working.types import Signal


class SideInputResolutionError(RuntimeError):
    """A declared side input could not be resolved to a value. Always names
    the side input so the failure points at exactly which binding is bad."""


def typed_step_value(result):
    """The typed value an `AdapterResult` represents, for stashing as a
    possible `earlier_step` binding target.

    Since ticket 10 that is simply `result.value`: every adapter populates
    it, and the per-kind carrier fields this used to fall back to are gone.
    A result with no `value` at all can't be resolved to a typed value and
    returns None, which `resolve_side_inputs` reports as an unresolved
    binding naming the side input.

    The `fs` argument went with the fallback that needed it — a `Signal`
    has always carried its own sample rate.
    """
    return result.value


def _resolve_library_exemplar(conn, name, binding):
    recording = q.get_recording(conn, binding["source_file"], binding["channel"])
    if recording is None:
        raise SideInputResolutionError(
            f"Side-input '{name}': no recording found for source_file="
            f"{binding['source_file']!r}, channel={binding['channel']}."
        )
    start_idx, end_idx = binding["start_idx"], binding["end_idx"]
    if start_idx < 0 or end_idx > recording["n_samples"]:
        raise SideInputResolutionError(
            f"Side-input '{name}': span [{start_idx}, {end_idx}) is outside "
            f"recording '{binding['source_file']}' channel {binding['channel']} "
            f"(n_samples={recording['n_samples']})."
        )
    # A true copy (not a view over the mmap, unlike `execution._load_signal`'s
    # root signal) — an exemplar slice is small, and a resolved binding must
    # not keep its source file's mmap handle open for the run's duration.
    x_full = np.load(recording["npy_path"], mmap_mode="r")
    x = np.array(x_full[start_idx:end_idx])
    return Signal(x=x, fs=recording["fs"])


def resolve_side_inputs(conn, spec, side_inputs, *, root_signal, step_results):
    """Resolve every side input `spec` (an `AdapterSpec`) declares to a
    typed value, ready to merge into the keyword arguments passed to
    `spec.run`.

    Parameters
    ----------
    conn : sqlite3.Connection
        Only used for a `library_exemplar` binding's recording lookup.
    spec : Adapters.base.AdapterSpec
        Its `side_inputs` (list of `SideInputSpec`) names what must resolve.
    side_inputs : dict
        The step's binding map (name -> binding), as built by
        `Working.recipes.make_recipe`.
    root_signal : Working.types.Signal
        The chain's root signal, for a `root_signal` binding.
    step_results : dict
        {step_index: typed value}, for an `earlier_step` binding — see
        `typed_step_value`.

    Returns
    -------
    dict : {side_input_name: resolved value}, one entry per `spec.side_inputs`.

    Raises
    ------
    SideInputResolutionError
        Naming the side input that could not be resolved — a missing
        binding, a binding whose source_kind the side input doesn't allow,
        an earlier step whose value isn't available, or a library exemplar
        that doesn't resolve against the database.
    """
    resolved = {}
    for side_input_spec in spec.side_inputs:
        name = side_input_spec.name
        binding = side_inputs.get(name)
        if binding is None:
            raise SideInputResolutionError(
                f"Side-input '{name}': '{spec.name}' declares this side input "
                f"but the step has no binding for it."
            )
        source_kind = binding.get("source_kind")
        if source_kind not in side_input_spec.sources:
            raise SideInputResolutionError(
                f"Side-input '{name}': bound source_kind {source_kind!r} is not "
                f"one of {side_input_spec.sources} this side input allows."
            )

        if source_kind == "root_signal":
            resolved[name] = root_signal

        elif source_kind == "earlier_step":
            value = step_results.get(binding["step_index"])
            if value is None:
                raise SideInputResolutionError(
                    f"Side-input '{name}': earlier step {binding['step_index']} "
                    f"has no resolvable typed value to bind."
                )
            resolved[name] = value

        elif source_kind == "library_exemplar":
            resolved[name] = _resolve_library_exemplar(conn, name, binding)

    return resolved
