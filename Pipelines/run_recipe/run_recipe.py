"""
run_recipe.py
===============
Headless CLI entry point for `Working.execution.execute_recipe` — runs a
recipe from a JSON file with no Panel/HoloViews/Datashader installed. This
is exactly what part 3's SLURM jobs wrap: the whole chain this script
calls into (`Working/`, `Adapters/`) never imports a UI library.

Recipe JSON shape (same as `Working.recipes.make_recipe`'s inputs)
--------------------------------------------------------------------
    {
        "recording_id": 1,
        "span": [100000, 100600],
        "steps": [
            {"stage": "preprocessing", "algorithm": "lowpass", "params": {"cutoff_hz": 0.05}},
            {"stage": "detection", "algorithm": "rupture", "params": {"penalty": 5.0}}
        ]
    }

`span` may be omitted or null for the whole channel.

Usage
-----
    python Pipelines/run_recipe/run_recipe.py --config path/to/recipe.json
    python Pipelines/run_recipe/run_recipe.py --config path/to/recipe.json --force
"""

# ── Repo-root bootstrap ───────────────────────────────────────────────────────
import sys as _sys
from pathlib import Path as _Path
_REPO_ROOT = _Path(__file__).resolve().parent
while not (_REPO_ROOT / "Working").is_dir() and _REPO_ROOT != _REPO_ROOT.parent:
    _REPO_ROOT = _REPO_ROOT.parent
if str(_REPO_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_REPO_ROOT))

import argparse
import json
import sys

from Working.execution import RecipeExecutionError, execute_recipe
from Working.recipes import make_recipe


def load_recipe_from_file(path):
    with open(path) as f:
        data = json.load(f)
    if "recording_id" not in data or "steps" not in data:
        raise ValueError(
            f"'{path}' doesn't look like a recipe (needs 'recording_id' and 'steps')."
        )
    return make_recipe(data["recording_id"], data["steps"], span=data.get("span"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, help="Path to a recipe JSON file.")
    parser.add_argument("--force", action="store_true",
                         help="Recompute even if a completed run for this exact recipe already exists.")
    parser.add_argument("--db", default=None, help="Override the database path.")
    args = parser.parse_args()

    recipe = load_recipe_from_file(args.config)
    print(f"recording_id={recipe['recording_id']}  span={recipe['span']}  "
          f"steps={[s['algorithm'] for s in recipe['steps']]}")

    def _progress(i, n, stage, algorithm):
        print(f"  [{i + 1}/{n}] {stage}.{algorithm} ...", flush=True)

    try:
        result = execute_recipe(recipe, db_path=args.db, force=args.force, on_progress=_progress)
    except RecipeExecutionError as e:
        print(f"FAILED: {e}", file=sys.stderr)
        sys.exit(1)

    status = "reused prior run" if result["reused"] else "computed"
    print(
        f"\nDone ({status}). run_id={result['run_id']}  config_hash={result['config_hash']}  "
        f"detections_written={result['detections_written']}"
    )
    for i, elapsed in sorted(result["step_timings"].items(), key=lambda kv: int(kv[0])):
        print(f"  step {i}: {elapsed:.3f}s")


if __name__ == "__main__":
    main()
