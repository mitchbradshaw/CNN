"""
execution.py
=============
Headless recipe execution — the core of part 2. Resolves each step of a
recipe through the adapter registry and runs them in order, each step's
output feeding the next, writing `runs`/`detections` to the database as it
goes. Importable and runnable from a bare script with no Panel installed
(see `run_recipe.py` for the CLI wrapper that part 3's SLURM jobs call).

Nothing here imports a UI library, directly or transitively — `Adapters/`
and `Working/` don't either, so this whole chain stays cluster-safe.

Step cache
----------
The executor caches a step's typed `Working.types` output to
`step_artifacts` when its measured runtime exceeds
`Working.config.STEP_CACHE_WRITE_THRESHOLD_S`. A cached step is restored
through the type's own `from_path` serialiser, never through a per-type
code path.

Interaction with `Working.encoding_cache`: it is **not used by the
executor**. `encoding_cache.py` remains the storage layer for the UI's
encoding-view lookups (SAX/Gramian encodings, keyed by whole-recipe hash).
The step cache stores typed step outputs (the seven `Working.types`) under
a recipe-*prefix* hash; it does not duplicate or replace `encoding_cache`.
"""

import datetime
import inspect
import json
import os
import time
import traceback

import numpy as np

from Adapters.base import AdapterResult
from Adapters.registry import discover_adapters, get_adapter
from Working.chain_validation import validate_recipe_steps
from Working.database import queries as q
from Working.database.runs import (
    find_completed_run,
    get_or_create_config,
    get_step_artifact,
    insert_artifact,
    insert_detection,
    insert_run,
    insert_step_artifact,
    list_detections,
    update_run,
)
from Working.recipes import recipe_hash
from Working.side_inputs import resolve_side_inputs, typed_step_value
from Working.types import Signal
import Working.types as interchange_types


class RecipeExecutionError(RuntimeError):
    """A step failed. The run row is already marked status='failed' with
    the traceback in error_text before this is raised."""


class RecipeCancelled(RuntimeError):
    """Cancelled via `should_cancel` between steps. The run row is marked
    status='failed' with a note, not left half-written."""


class HeldOutRecordingLocked(RuntimeError):
    """Raised when attempting to execute a recipe on the held-out recording
    without explicitly unlocking it first."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _referenced_earlier_steps(steps):
    """Indices any step's `earlier_step` side-input binding points at —
    the only step results worth keeping around. Without this, resolving a
    later `earlier_step` binding would mean retaining every intermediate
    signal for the whole run, defeating `_load_signal`'s memory-mapping
    care for chains that never actually reference an earlier step."""
    referenced = set()
    for step in steps:
        for binding in (step.get("side_inputs") or {}).values():
            if binding.get("source_kind") == "earlier_step":
                referenced.add(binding["step_index"])
    return referenced


def _load_signal(recording, span):
    """Memory-map the channel and slice out `span` (or the whole channel
    if span is None) — only the requested span pages in off disk."""
    x_full = np.load(recording["npy_path"], mmap_mode="r")
    if span is None:
        start, end = 0, recording["n_samples"]
    else:
        start, end = span
    x = np.asarray(x_full[start:end])
    t = np.arange(start, end) / recording["fs"]
    return x, t


_TYPED_VALUE_CLASSES = {name.lower(): getattr(interchange_types, name)
                        for name in interchange_types.__all__}


def _recipe_prefix_hash(recipe, up_to_index):
    """The step-cache key: hash of the recipe prefix through `up_to_index`.

    The prefix is a full recipe whose `steps` are truncated after the step,
    so every field that affects the step — recording, span, params, and any
    side-input bindings on the prefix steps — enters the hash.
    """
    prefix = dict(recipe)
    prefix["steps"] = recipe["steps"][:up_to_index + 1]
    return recipe_hash(prefix)


def _load_cached_result(spec, cached_path):
    """Load a cached typed step output into an `AdapterResult`.

    Returns None when `spec.output_kind` has no `Working.types` serialiser
    or the cached directory is missing/corrupt, so the caller falls back to
    recomputation.

    Every kind restores the same way since ticket 10 — `value` is the only
    payload, so `signal` no longer needs the special case that rebuilt an
    `(x, t)` pair, and the run's time axis (which a `Signal` cannot carry,
    having no absolute offset) stays the one the caller already holds.
    """
    value_cls = _TYPED_VALUE_CLASSES.get(spec.output_kind)
    if value_cls is None or not os.path.isdir(cached_path):
        return None
    try:
        value = value_cls.from_path(cached_path)
    except Exception:
        return None
    return AdapterResult(output_kind=spec.output_kind, value=value)


def _cache_step_result(conn, recipe, step_index, result, elapsed_s, fs, cache_root,
                       threshold_s):
    """Persist a step's typed output to `step_artifacts` when it was slow
    enough to be worth the disk. No eviction — missing/corrupt cached
    directories are simply overwritten on the next recomputation."""
    if elapsed_s <= threshold_s:
        return
    value = typed_step_value(result)
    if value is None or not isinstance(value, tuple(_TYPED_VALUE_CLASSES.values())):
        return
    prefix_hash = _recipe_prefix_hash(recipe, step_index)
    cache_dir = os.path.join(cache_root, prefix_hash, str(step_index))
    value.to_path(cache_dir)
    insert_step_artifact(conn, prefix_hash, step_index, cache_dir)


def execute_recipe(recipe, db_path=None, force=False, on_progress=None, should_cancel=None,
                   run_kwargs=None, on_step_result=None):
    """Run every step of `recipe` in order.

    Idempotent: if a completed run already exists for this exact recipe
    (by recipe hash) over this exact (recording, span), it's reused —
    detections are read back from the database rather than recomputed —
    unless `force=True`.

    Crash-safe: the `runs` row is inserted with status='running' before any
    step executes; any exception (including cancellation) updates it to
    status='failed' with `error_text` (a full traceback) before re-raising.
    Nothing is left half-written.

    Parameters
    ----------
    recipe : dict
        As built by `Working.recipes.make_recipe`.
    db_path : str, optional
        Passed through to `Working.database.schema.init_db`.
    force : bool
        Recompute even if a completed run for this exact recipe already exists.
    on_progress : callable(step_index, n_steps, stage, algorithm), optional
        Called before each step starts. Lets a caller (e.g. a UI background
        thread) show progress without this module knowing how progress is
        displayed.
    should_cancel : callable() -> bool, optional
        Checked before each step. Cancellation is only ever between steps —
        an in-progress numpy/scipy call isn't interrupted mid-flight.
    run_kwargs : dict, optional
        Extra keyword arguments forwarded to `spec.run(...)` for whichever
        steps' `run` callable actually declares them (checked via
        `inspect.signature`, silently dropped for steps that don't — most
        adapters don't and must keep working unmodified). Deliberately NOT
        part of `params`: these are execution-time callables/handles (e.g. a
        finer-grained `on_progress(done, total, stage)` a slow adapter's own
        internal loop can drive — WINDOW_MATRIX_UI_PROMPT.md §6.1), not
        recipe state, so they must never enter `get_or_create_config`'s hash
        or a step's persisted `params`. This is a DIFFERENT progress
        granularity from the `on_progress` above: this module's callback
        fires once per STEP; a step's own `run_kwargs["on_progress"]`, if it
        uses one, fires at whatever finer grain that adapter defines (e.g.
        once per window) — the two must not be conflated into one signature.
    on_step_result : callable(step_index, result), optional
        Called after each step's result lands, with the step index and that
        step's `AdapterResult`. Lets a caller render/emit each stage as it
        completes rather than waiting for the whole run — the "per-stage
        results as they land" behaviour (PIPELINE_PRD.md, Execution). Fires
        for cached and recomputed steps alike, after the step's detections
        and any `persist` artifact have been written, so the callback sees a
        fully-landed stage. This is a distinct channel from `on_progress`
        (before the step) and from `run_kwargs["on_progress"]` (inside the
        step at the adapter's own granularity).

    Returns
    -------
    dict : {
        "run_id": int, "reused": bool, "result": AdapterResult or None,
        "step_timings": {step_index: elapsed_s}, "detections_written": int,
        "config_hash": str,
    }
    `result` is the last step's `AdapterResult` (None for a reused run,
    since nothing was recomputed — read `detections` from the database for
    a reused run's output instead).
    """
    discover_adapters()  # idempotent; makes sure every adapter self-registers

    from Working.database.schema import init_db
    conn = init_db(db_path)

    try:
        return _execute_recipe_with_conn(
            conn, recipe, force, on_progress, should_cancel, run_kwargs, on_step_result,
        )
    finally:
        # This function always opens its own fresh connection (unlike the
        # UI, which keeps one open for an app's whole lifetime) — nothing
        # outside this call needs it afterwards, and leaving it open holds
        # a file lock that trips up an immediate re-open (e.g. a caller
        # unlinking the db file right after, or a bare-script test that
        # calls execute_recipe() several times against the same db_path).
        conn.close()


def _execute_recipe_with_conn(conn, recipe, force, on_progress, should_cancel, run_kwargs=None,
                              on_step_result=None):
    from Working.config import (
        HELD_OUT_RECORDING_FILE,
        HELD_OUT_UNLOCK,
        STEP_CACHE_ROOT,
        STEP_CACHE_WRITE_THRESHOLD_S,
    )

    recording = q.get_recording_by_id(conn, recipe["recording_id"])
    if recording is None:
        raise ValueError(f"No recording with id={recipe['recording_id']}")

    # Guard against accessing the held-out recording unless explicitly unlocked
    if not HELD_OUT_UNLOCK and recording["source_file"] == HELD_OUT_RECORDING_FILE:
        raise HeldOutRecordingLocked(
            f"Access to held-out recording '{HELD_OUT_RECORDING_FILE}' is locked. "
            f"Set HELD_OUT_UNLOCK=True in Working/config.py to temporarily allow access."
        )

    # Hard-fail before any computation (or run row) — a hand-edited or
    # cluster-generated recipe that bypassed `Working.recipes.make_recipe`
    # must not get partway through a long run before failing. Same seam
    # `make_recipe` uses, so the two layers can't drift apart.
    ok, reason = validate_recipe_steps(recipe["steps"])
    if not ok:
        raise ValueError(f"Invalid chain: {reason}")

    span = recipe["span"]
    span_start = 0 if span is None else span[0]
    span_end = recording["n_samples"] if span is None else span[1]

    config_id, hash8 = get_or_create_config(conn, recipe)

    if not force:
        existing = find_completed_run(conn, config_id, recipe["recording_id"], span_start, span_end)
        if existing is not None:
            existing_detections = list_detections(conn, existing["id"])
            return {
                "run_id": existing["id"],
                "reused": True,
                "result": None,
                "step_timings": json.loads(existing["step_timings_json"] or "{}"),
                "detections_written": len(existing_detections),
                "config_hash": hash8,
            }

    run_id = insert_run(conn, config_id, recipe["recording_id"], span_start, span_end, status="running")

    try:
        x, t = _load_signal(recording, span)
        fs = recording["fs"]
        root_signal = Signal(x=x, fs=fs)

        step_timings = {}
        result = None
        current_value = None  # last non-signal typed result (e.g. Scores), for a
                               # downstream step whose `run` declares a `value` param
        detections_written = 0
        n_steps = len(recipe["steps"])
        referenced_steps = _referenced_earlier_steps(recipe["steps"])
        step_results = {}

        for i, step in enumerate(recipe["steps"]):
            if should_cancel is not None and should_cancel():
                raise RecipeCancelled(f"Cancelled before step {i} ({step['stage']}.{step['algorithm']}).")

            # The run row is the poller's progress channel: record which step
            # is about to execute so a UI can read status/current_step/error
            # off the row without any callback plumbing. Set AFTER the cancel
            # check, so a cancellation never claims a step actually started.
            update_run(conn, run_id, current_step=i)

            if on_progress is not None:
                on_progress(i, n_steps, step["stage"], step["algorithm"])

            adapter_name = f"{step['stage']}.{step['algorithm']}"
            spec = get_adapter(adapter_name)
            params = spec.validate_params(step.get("params"))

            if spec.max_span_samples is not None and len(x) > spec.max_span_samples:
                raise ValueError(
                    f"Step {i} ('{adapter_name}'): span is {len(x)} samples, which "
                    f"exceeds this adapter's max_span_samples={spec.max_span_samples}. "
                    "Choose a smaller span — this is an O(n^2)-or-worse encoding "
                    "and a larger span would attempt to allocate a matrix whose "
                    "size scales with the square of the span length."
                )

            # Resume walk: the cache key is the recipe prefix through this
            # step. A hit restores the step's typed output from disk and
            # skips `spec.run`; a miss computes it and (if slow enough)
            # writes the next cache entry.
            prefix_hash = _recipe_prefix_hash(recipe, i)
            cached = get_step_artifact(conn, prefix_hash, i)
            result = _load_cached_result(spec, cached["path"]) if cached is not None else None
            from_cache = result is not None

            if from_cache:
                step_timings[i] = 0.0
            else:
                accepted = inspect.signature(spec.run).parameters
                extra = {}
                if run_kwargs:
                    extra = {k: v for k, v in run_kwargs.items() if k in accepted}
                if spec.side_inputs:
                    extra.update(resolve_side_inputs(
                        conn, spec, step.get("side_inputs") or {},
                        root_signal=root_signal, step_results=step_results,
                    ))
                # A typed (non-root-signal) step whose `run` declares a `value`
                # param receives the previous typed step's output directly —
                # this is what lets a chain like matrix_profile -> threshold
                # thread a `Scores` through without going back via (x, t).
                if spec.input_kind is not None and "value" in accepted:
                    extra["value"] = current_value

                t0 = time.time()
                result = spec.run(x, t, fs, **params, **extra)
                step_timings[i] = time.time() - t0
                _cache_step_result(
                    conn, recipe, i, result, step_timings[i], fs,
                    STEP_CACHE_ROOT, STEP_CACHE_WRITE_THRESHOLD_S,
                )

            if i in referenced_steps:
                step_results[i] = typed_step_value(result)

            if result.output_kind == "signal":
                # `t` is the span's absolute time axis (`_load_signal`), and a
                # `Signal` carries `fs` but no absolute offset — so it is
                # rebuilt from this step's own axis rather than taken off the
                # value. Every signal block filters in place and preserves the
                # sample count; one that did not would silently misalign every
                # downstream plot against the channel, so it is refused here.
                x = result.value.x
                if len(x) != len(t):
                    raise RecipeExecutionError(
                        f"Step {i} ('{adapter_name}') returned {len(x)} sample(s) "
                        f"from a {len(t)}-sample span. A 'signal' block must "
                        "preserve the sample count: the chain's time axis is the "
                        "span's, and Signal carries no absolute offset to rebuild "
                        "a different one from."
                    )
            elif result.output_kind == "spanset":
                span_set = result.value
                span_scores = span_set.scores or (None,) * len(span_set.starts)
                for start_idx, end_idx, score in zip(span_set.starts, span_set.ends, span_scores):
                    insert_detection(conn, run_id, int(start_idx), int(end_idx),
                                      score=score, commit=False)
                    detections_written += 1
                conn.commit()

            if result.value is not None:
                current_value = result.value

            if spec.persist is not None and not from_cache:
                # Opt-in only (see AdapterSpec.persist's docstring) — an
                # adapter that declares this hook gets its output written
                # to disk and registered automatically, so a headless
                # run_recipe.py invocation (e.g. an HPC job) produces a
                # browsable artifact with no separate import step. Any of
                # the seven types may declare `persist`, not just 'encoding'.
                # Skipped on a cache hit because only the typed value was
                # restored, not the adapter's raw persist payload.
                artifact_path = spec.persist(
                    conn, run_id, hash8, recording, span_start, span_end, params, result
                )
                if artifact_path is not None:
                    insert_artifact(conn, run_id, kind="encoding", path=artifact_path)

            # Emit the stage as it lands — after detections are committed and
            # any persist artifact is written, so the callback sees a fully
            # landed result. Fires for cached and recomputed steps alike.
            if on_step_result is not None:
                on_step_result(i, result)

        duration_s = sum(step_timings.values())
        update_run(
            conn, run_id, status="completed", finished_at=_now(),
            duration_s=duration_s, step_timings_json=json.dumps(step_timings),
        )

        return {
            "run_id": run_id, "reused": False, "result": result,
            "step_timings": step_timings, "detections_written": detections_written,
            "config_hash": hash8,
        }

    except RecipeCancelled as e:
        update_run(conn, run_id, status="failed", finished_at=_now(), error_text=str(e))
        raise
    except Exception as e:
        tb = traceback.format_exc()
        update_run(conn, run_id, status="failed", finished_at=_now(), error_text=tb)
        raise RecipeExecutionError(f"Recipe execution failed (run_id={run_id}): {e}") from e
