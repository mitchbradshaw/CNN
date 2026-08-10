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
"""

import datetime
import inspect
import json
import time
import traceback

import numpy as np

from Adapters.registry import discover_adapters, get_adapter
from Working.database import queries as q
from Working.database.runs import (
    find_completed_run,
    get_or_create_config,
    insert_artifact,
    insert_detection,
    insert_run,
    list_detections,
    update_run,
)


class RecipeExecutionError(RuntimeError):
    """A step failed. The run row is already marked status='failed' with
    the traceback in error_text before this is raised."""


class RecipeCancelled(RuntimeError):
    """Cancelled via `should_cancel` between steps. The run row is marked
    status='failed' with a note, not left half-written."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


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


def execute_recipe(recipe, db_path=None, force=False, on_progress=None, should_cancel=None,
                   run_kwargs=None):
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
        return _execute_recipe_with_conn(conn, recipe, force, on_progress, should_cancel, run_kwargs)
    finally:
        # This function always opens its own fresh connection (unlike the
        # UI, which keeps one open for an app's whole lifetime) — nothing
        # outside this call needs it afterwards, and leaving it open holds
        # a file lock that trips up an immediate re-open (e.g. a caller
        # unlinking the db file right after, or a bare-script test that
        # calls execute_recipe() several times against the same db_path).
        conn.close()


def _execute_recipe_with_conn(conn, recipe, force, on_progress, should_cancel, run_kwargs=None):
    recording = q.get_recording_by_id(conn, recipe["recording_id"])
    if recording is None:
        raise ValueError(f"No recording with id={recipe['recording_id']}")

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

        step_timings = {}
        result = None
        detections_written = 0
        n_steps = len(recipe["steps"])

        for i, step in enumerate(recipe["steps"]):
            if should_cancel is not None and should_cancel():
                raise RecipeCancelled(f"Cancelled before step {i} ({step['stage']}.{step['algorithm']}).")

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

            extra = {}
            if run_kwargs:
                accepted = inspect.signature(spec.run).parameters
                extra = {k: v for k, v in run_kwargs.items() if k in accepted}

            t0 = time.time()
            result = spec.run(x, t, fs, **params, **extra)
            step_timings[i] = time.time() - t0

            if result.output_kind == "signal":
                x, t = result.x, result.t
            elif result.output_kind == "intervals":
                for interval in result.intervals:
                    start_idx, end_idx = interval[0], interval[1]
                    score = interval[2] if len(interval) > 2 else None
                    insert_detection(conn, run_id, int(start_idx), int(end_idx),
                                      score=score, commit=False)
                    detections_written += 1
                conn.commit()
            elif result.output_kind == "encoding" and spec.persist is not None:
                # Opt-in only (see AdapterSpec.persist's docstring) — an
                # adapter that declares this hook gets its output written
                # to disk and registered automatically, so a headless
                # run_recipe.py invocation (e.g. an HPC job) produces a
                # browsable artifact with no separate import step.
                artifact_path = spec.persist(
                    conn, run_id, hash8, recording, span_start, span_end, params, result
                )
                if artifact_path is not None:
                    insert_artifact(conn, run_id, kind="encoding", path=artifact_path)
            # Every other 'encoding' output is left on `result` for the
            # caller — caching is a separate, explicit decision (see
            # Working.encoding_cache), not something every
            # encoding-producing step does automatically.

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
