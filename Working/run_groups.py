"""
run_groups.py
===============
Fan-out over a channel or band scope (ticket 25). One action over N
channels or N bands creates one `run_groups` row and N `runs` rows
referencing it; locally the N runs execute sequentially with per-item
progress; on the cluster a single SLURM array job's task index selects its
own target from the target list baked into the recipe.

A channel fan-out and a band fan-out are deliberately the same mechanism
(PIPELINE_PRD.md, Execution: Fan-out and Band decomposition). The recipe
carries an optional `fan_out` scope:

    {"kind": "channels", "targets": [recording_id, ...]}
    {"kind": "bands",    "targets": [{"label": ..., "low_hz": ..., "high_hz": ...}, ...]}

Band labels are caller-supplied and are NOT redefined here — a caller may
reuse the existing `Working.database.bands` vocabulary to name its fan-out
targets, rather than this module growing a parallel band list.

`materialize_target` turns one target index into a plain per-target recipe
(a channel target becomes the recipe's `recording_id`; a band target gets a
bandpass step prepended). `fan_out_recipe` runs every target, linking each
run row to the shared run-group row.

No UI imports — cluster-safe, headless-test-safe, same as `Working.execution`.
"""

from Working.database import runs as R
from Working.recipes import make_recipe


def _surrogate_enabled(recipe, surrogate):
    """Resolve the surrogate switch from the explicit argument or the
    recipe's recorded `surrogate` control. `None` means "use the recipe",
    which in turn defaults to off for headless callers that never set it."""
    if surrogate is not None:
        return bool(surrogate)
    return bool(recipe.get("surrogate", False))


def surrogate_recipe(recipe, params=None):
    """Build the paired null recipe: the identical chain with a
    `preprocessing.surrogate` step prepended.

    The `fan_out` scope and the `surrogate` control key are stripped — this
    is a plain per-target recipe, and the surrogate run records its
    provenance in `runs.surrogate_of_run_id`, not in its recipe.
    """
    step = {
        "stage": "preprocessing",
        "algorithm": "surrogate",
        "params": dict(params or {"method": "phase_randomize", "seed": 0}),
    }
    surrogate = dict(recipe)
    surrogate["steps"] = [step] + recipe["steps"]
    surrogate.pop("fan_out", None)
    surrogate.pop("surrogate", None)
    return surrogate


def run_paired_recipe(recipe, db_path=None, force=False, on_progress=None,
                      should_cancel=None, run_kwargs=None, on_step_result=None,
                      surrogate=None, surrogate_params=None):
    """Run a single recipe, optionally paired with its surrogate null.

    The original recipe always records the resolved `surrogate` switch in its
    stored config (so an explicitly-off control is visible rather than simply
    absent). When the switch is on, a second run executes the identical chain
    with `preprocessing.surrogate` prepended and is linked to the original by
    `runs.surrogate_of_run_id`.

    Returns
    -------
    dict : the `execute_recipe` result for the original run, plus
    `surrogate_run_id` (None when off) and `surrogate_result` (the
    surrogate run's `execute_recipe` result, when on).
    """
    from Working.database.schema import init_db
    from Working.execution import execute_recipe

    enabled = _surrogate_enabled(recipe, surrogate)
    original_recipe = dict(recipe)
    original_recipe["surrogate"] = bool(enabled)

    original = execute_recipe(
        original_recipe, db_path=db_path, force=force,
        should_cancel=should_cancel, run_kwargs=run_kwargs,
        on_step_result=on_step_result, on_progress=on_progress,
    )
    out = dict(original)
    out["surrogate_run_id"] = None
    if not enabled:
        return out

    conn = init_db(db_path)
    try:
        surrogate_run = execute_recipe(
            surrogate_recipe(original_recipe, surrogate_params),
            db_path=db_path, force=force,
            should_cancel=should_cancel, run_kwargs=run_kwargs,
            on_progress=on_progress,
        )
        R.update_run(conn, surrogate_run["run_id"],
                     surrogate_of_run_id=original["run_id"])
        out["surrogate_run_id"] = surrogate_run["run_id"]
        out["surrogate_result"] = surrogate_run
        return out
    finally:
        conn.close()


def target_for_index(recipe, target_index):
    """The raw fan-out target for a given index — what a cluster task index
    selects from the baked-in list."""
    return recipe["fan_out"]["targets"][target_index]


def materialize_target(recipe, target_index):
    """Build the plain per-target recipe for one fan-out target.

    The returned recipe has no `fan_out` scope of its own: a channel target
    becomes the recipe's `recording_id`, a band target gets a bandpass step
    prepended. Rebuilt through `Working.recipes.make_recipe` so the chain is
    re-validated exactly as an ordinary hand-built recipe would be.
    """
    fan = recipe["fan_out"]
    target = fan["targets"][target_index]
    if fan["kind"] == "channels":
        return make_recipe(target, recipe["steps"], span=recipe["span"])
    bandpass_step = {
        "stage": "preprocessing",
        "algorithm": "bandpass",
        "params": {"low_hz": target["low_hz"], "high_hz": target["high_hz"]},
    }
    return make_recipe(
        recipe["recording_id"], [bandpass_step] + recipe["steps"], span=recipe["span"],
    )


def fan_out_recipe(recipe, db_path=None, force=False, on_progress=None,
                   should_cancel=None, run_kwargs=None, on_step_result=None,
                   surrogate=None, surrogate_params=None):
    """Execute every target of a fan-out recipe sequentially.

    One `run_groups` row is created, each target is materialised into a plain
    per-target recipe and executed through `Working.execution.execute_recipe`,
    and the resulting run row is linked to the group via `run_group_id`. With
    `surrogate` on, each target is run as a paired surrogate run and both the
    original and surrogate run rows are linked to the shared group.

    Parameters
    ----------
    recipe : dict
        A recipe carrying a `fan_out` scope, as built by
        `Working.recipes.make_recipe(..., fan_out=...)`.
    db_path : str, optional
        Passed through to `execute_recipe`.
    force : bool
        Recompute each target even if a completed run already exists.
    on_progress : callable(index, total, label), optional
        Fired once per target before it executes, so a caller can show
        per-item progress across the fan-out. This is the fan-out's own
        progress channel, distinct from `execute_recipe`'s per-step
        `on_progress`.
    surrogate : bool, optional
        If None, the recipe's recorded `surrogate` control is used. When
        True, each per-target run is paired with a surrogate null run linked
        by `runs.surrogate_of_run_id`.
    surrogate_params : dict, optional
        Params for the prepended `preprocessing.surrogate` step.
    should_cancel, run_kwargs, on_step_result
        Forwarded unchanged to `execute_recipe` for each target.

    Returns
    -------
    dict : {
        "run_group_id": int,
        "runs": [{"run_id": int, "target": target, "reused": bool,
                  "config_hash": str, "detections_written": int,
                  "surrogate_run_id": int | None,
                  "surrogate_detections_written": int | None}, ...],
    }
    """
    if "fan_out" not in recipe:
        raise ValueError("Recipe has no fan_out scope; nothing to fan out.")

    from Working.database.schema import init_db

    enabled = _surrogate_enabled(recipe, surrogate)

    conn = init_db(db_path)
    try:
        group_id = R.create_run_group(conn)
        fan = recipe["fan_out"]
        targets = fan["targets"]
        n_targets = len(targets)
        runs_out = []
        for i, target in enumerate(targets):
            if on_progress is not None:
                label = target if fan["kind"] == "channels" else target["label"]
                on_progress(i, n_targets, label)
            per_target = materialize_target(recipe, i)
            per_target["surrogate"] = enabled
            result = run_paired_recipe(
                per_target, db_path=db_path, force=force,
                should_cancel=should_cancel, run_kwargs=run_kwargs,
                on_step_result=on_step_result,
                surrogate=enabled, surrogate_params=surrogate_params,
            )
            R.update_run(conn, result["run_id"], run_group_id=group_id)
            surrogate_detections = None
            if result.get("surrogate_run_id") is not None:
                R.update_run(conn, result["surrogate_run_id"],
                             run_group_id=group_id)
                surrogate_detections = result["surrogate_result"]["detections_written"]
            runs_out.append({
                "run_id": result["run_id"],
                "target": target,
                "reused": result["reused"],
                "config_hash": result["config_hash"],
                "detections_written": result["detections_written"],
                "surrogate_run_id": result.get("surrogate_run_id"),
                "surrogate_detections_written": surrogate_detections,
            })
        return {"run_group_id": group_id, "runs": runs_out}
    finally:
        conn.close()
