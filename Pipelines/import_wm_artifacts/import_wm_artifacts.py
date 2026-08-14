"""
import_wm_artifacts.py
========================
One-shot, idempotent backfill of the pre-v1 window-matrix CSVs in
`MATRICES/` into the v1 `.npz` format and the `configs`/`runs`/`artifacts`
registry (WINDOW_MATRIX_UI_PROMPT.md §5).

Safe to re-run: `get_or_create_config` is idempotent on recipe hash, and an
existing completed run over the same (recording, span) short-circuits, so a
second invocation writes nothing and moves nothing.

Usage
-----
  python Pipelines/import_wm_artifacts/import_wm_artifacts.py            # report only
  python Pipelines/import_wm_artifacts/import_wm_artifacts.py --apply    # actually import
  python Pipelines/import_wm_artifacts/import_wm_artifacts.py --apply \
      --assume "M2_concat_fs1_10min_27118wins_consecutive.csv=CH2"

Report-only is the default deliberately. The interesting cases here are the
files whose identity is NOT recoverable, and those need a human decision
before anything is written or moved.

What is and is not recoverable
------------------------------
Only `{stem}_CH{n}_WIN{n}min_STEP{n}pct.csv` — the naming
`build_window_matrix.py` produces — is fully self-describing. Of the files
actually present:

  M2_concat_fs1_10min_27118wins_consecutive.csv
      timescale (10 min) and window count are recoverable; the CHANNEL is
      not, and nothing inside the file records it. Requires --assume.

  features.csv, features - Copy.csv, features_graph.csv
      no recoverable identity at all — no source file, no channel, no
      timescale, no sample rate. Reported and left in place. ("- Copy" also
      means the relationship between the first two is unknown; guessing that
      they are the same matrix would be inventing provenance.)

  0.01_percent_M2_concat_fs1.mat_step0.5.csv
  0.01_percent_M2_concat_fs1_consecutive.csv
      a 0.01 % subsample, not a matrix over a contiguous channel span. The
      `start_idx` values do not index the real channel, so importing them
      would attach wrong spans to real recordings. Reported and skipped.

The `computed` mask on a backfilled matrix is INFERRED as `~isnan(values)`
and the artifact is flagged `backfilled=True`. Nothing can recover the
"never attempted" / "attempted, NaN" distinction retroactively
(WINDOW_MATRIX_UI_PROMPT.md §0.2); recording that it is unrecoverable is
the honest option, and the flag is what stops a resume from trusting it.
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
import os
import re
import shutil

import numpy as np
import pandas as pd

from Working.database import queries as q
from Working.database.matrix_profile_store import compute_data_sha1
from Working.database.runs import get_or_create_config, insert_artifact, insert_run
from Working.database.schema import init_db
from Working.database import window_matrix_store as store
from Working.recipes import make_recipe

MATRICES_DIR = "MATRICES"
LEGACY_DIR = os.path.join(MATRICES_DIR, "_legacy")

# Columns dropped on import, per WINDOW_MATRIX_UI_PROMPT.md §2.1. Matched by
# exact name or by prefix; everything else numeric is kept.
_DROP_EXACT = {
    "category", "fusion_pred_v1", "fusion_pred_v1_error",
    "rf_p_notinteresting", "cnn_1_minus_p_notinteresting",
    "mean", "std_dev", "entropy",
}
_DROP_PREFIX = ("stft_bin_", "Unnamed:", "psax_", "csax_", "dsax_")
_DROP_SUFFIX = ("_notinteresting",)

# `{stem}_CH{n}_WIN{n}min_STEP{n}pct.csv`
_FULL_RE = re.compile(
    r"^(?P<stem>.+?)_CH(?P<channel>\d+)_WIN(?P<window>[\d.]+)min"
    r"_STEP(?P<step>\d+)pct$"
)
# `{stem}_{n}min_...` — timescale only, no channel
_PARTIAL_RE = re.compile(r"^(?P<stem>.+?)_(?P<window>[\d.]+)min_")


def _should_drop(column):
    name = str(column)
    if name in _DROP_EXACT:
        return True
    if any(name.startswith(p) for p in _DROP_PREFIX):
        return True
    if any(name.endswith(s) for s in _DROP_SUFFIX):
        return True
    return False


def parse_filename(filename):
    """What a filename can be trusted to say about the matrix inside it.

    Returns a dict with `stem`, `channel`, `window_min`, `step_frac` — any
    of which may be None — plus `missing`, the list of fields that could not
    be recovered. Never guesses: a field the name does not carry comes back
    None, not a default.
    """
    base = os.path.splitext(os.path.basename(filename))[0]
    out = {"stem": None, "channel": None, "window_min": None, "step_frac": None}

    match = _FULL_RE.match(base)
    if match:
        out.update(
            stem=match.group("stem"),
            channel=int(match.group("channel")),
            window_min=float(match.group("window")),
            step_frac=int(match.group("step")) / 100.0,
        )
    else:
        match = _PARTIAL_RE.match(base)
        if match:
            out.update(stem=match.group("stem"), window_min=float(match.group("window")))
            # "consecutive" is the old word for non-overlapping windows.
            if "consecutive" in base:
                out["step_frac"] = 1.0

    out["missing"] = [k for k in ("stem", "channel", "window_min", "step_frac")
                      if out[k] is None]
    return out


def _read_matrix_csv(path):
    """Load a pre-v1 CSV into a start_idx-indexed frame, handling the three
    ways `start_idx` was written across these files."""
    df = pd.read_csv(path)
    if "start_idx" in df.columns:
        df = df.set_index("start_idx")
    elif len(df.columns) and str(df.columns[0]).startswith("Unnamed: 0"):
        df = df.rename(columns={df.columns[0]: "start_idx"}).set_index("start_idx")
    else:
        raise ValueError("no start_idx column and no unnamed index column")
    df.index = df.index.astype(np.int64)
    return df.sort_index()


def _grid_from_index(index):
    """`(step, uniform)` from the start-index sequence.

    A non-uniform spacing means the filename's timescale does not describe
    the grid, and importing it under that timescale would attach a wrong
    geometry to a real recording — so this is reported as a hard failure,
    not smoothed over by taking the modal difference.
    """
    if len(index) < 2:
        return None, False
    diffs = np.diff(np.asarray(index, dtype=np.int64))
    uniques = np.unique(diffs)
    if len(uniques) == 1 and uniques[0] > 0:
        return int(uniques[0]), True
    return None, False


def plan_file(conn, path, assume_channel=None):
    """Decide what to do with one CSV, without writing anything.

    Returns a dict with `action` in {"import", "skip"}, a `reason`, and —
    for importable files — everything `apply_plan` needs.
    """
    name = os.path.basename(path)
    plan = {"path": path, "name": name, "action": "skip", "reason": None}

    if name.startswith("0.01_percent"):
        plan["reason"] = (
            "a 0.01 % subsample, not a contiguous channel span — its start_idx "
            "values do not index the real channel, so importing it would attach a "
            "wrong span to a real recording."
        )
        return plan

    parsed = parse_filename(name)
    if assume_channel is not None:
        parsed["channel"] = assume_channel
        parsed["missing"] = [k for k in parsed["missing"] if k != "channel"]

    if parsed["stem"] is None or parsed["window_min"] is None:
        plan["reason"] = (
            "no recoverable identity in the filename (no source stem and/or no "
            "timescale), and nothing inside the file records it."
        )
        return plan
    if parsed["channel"] is None:
        plan["reason"] = (
            f"timescale ({parsed['window_min']:g} min) is recoverable but the CHANNEL "
            f"is not. Re-run with --assume \"{name}=CH<n>\" once you know which "
            "channel this is."
        )
        return plan
    if parsed["step_frac"] is None:
        plan["reason"] = "step fraction is not recoverable from the filename."
        return plan

    source_file = f"{parsed['stem']}.mat"
    recording = q.get_recording(conn, source_file, parsed["channel"])
    if recording is None:
        # The stem may already carry the extension, or the recording may be
        # registered under the .npy name — try the raw stem too before giving up.
        recording = q.get_recording(conn, parsed["stem"], parsed["channel"])
    if recording is None:
        plan["reason"] = (
            f"no recording registered for source_file='{source_file}' "
            f"channel={parsed['channel']}. Materialise the channel first "
            "(Pipelines/materialize_channels)."
        )
        return plan

    try:
        df = _read_matrix_csv(path)
    except Exception as exc:
        plan["reason"] = f"unreadable: {exc}"
        return plan

    if df.empty:
        plan["reason"] = "no rows."
        return plan

    step, uniform = _grid_from_index(df.index)
    m = store.window_samples(parsed["window_min"], recording["fs"])
    if not uniform:
        plan["reason"] = (
            "start_idx spacing is not uniform, so the filename's timescale does not "
            "describe this grid. Importing it under that timescale would record a "
            "geometry the file does not have."
        )
        return plan

    expected_step = store.step_samples(m, parsed["step_frac"])
    if step != expected_step:
        plan["reason"] = (
            f"observed step is {step:,} samples but "
            f"WIN{parsed['window_min']:g}min/STEP{parsed['step_frac']:.0%} at "
            f"fs={recording['fs']:g} implies {expected_step:,}. The filename and the "
            "contents disagree about the geometry."
        )
        return plan

    kept = [c for c in df.columns if not _should_drop(c)]
    dropped = [c for c in df.columns if _should_drop(c)]
    numeric = [c for c in kept if pd.api.types.is_numeric_dtype(df[c])]
    non_numeric = [c for c in kept if c not in numeric]
    if not numeric:
        plan["reason"] = "no numeric measure columns survive the §2.1 exclusions."
        return plan

    span_start = int(df.index[0])
    span_end = int(df.index[-1]) + m

    plan.update(
        action="import",
        recording=recording,
        window_min=parsed["window_min"],
        step_frac=parsed["step_frac"],
        m=m, step=step,
        columns=numeric,
        dropped_columns=dropped,
        dropped_non_numeric=non_numeric,
        n_windows=len(df),
        span=(span_start, span_end),
        frame=df,
    )
    return plan


def apply_plan(conn, plan, results_dir=store.DEFAULT_RESULTS_DIR,
               legacy_dir=LEGACY_DIR, move_original=True):
    """Write the v1 artifact and register it. Idempotent."""
    recording = plan["recording"]
    df = plan["frame"][plan["columns"]]

    recipe = make_recipe(recording["id"], [
        {"stage": "preprocessing", "algorithm": "window_matrix",
         "params": {"window_min": float(plan["window_min"]),
                    "step_frac": float(plan["step_frac"])}},
    ], span=list(plan["span"]))
    config_id, config_hash = get_or_create_config(conn, recipe)

    existing = store.find_wm(conn, recording["id"], plan["window_min"],
                             step_frac=plan["step_frac"], span=plan["span"])
    if existing is not None:
        return {"status": "already-imported", "artifact_path": existing["artifact_path"],
                "run_id": existing["run_id"]}

    values = df.to_numpy(dtype=np.float32)
    # Inferred, not recorded — see the module docstring. `backfilled=True`
    # is what tells a later resume not to trust this mask.
    computed = np.isfinite(values)

    sha1 = (compute_data_sha1(recording["npy_path"])
            if os.path.isfile(recording["npy_path"]) else "")

    artifact_path = store.save_wm(
        values, computed, list(df.columns), df.index.to_numpy(dtype=np.int64),
        m=plan["m"], step=plan["step"], fs=recording["fs"],
        window_min=plan["window_min"], step_frac=plan["step_frac"],
        span_start=plan["span"][0], span_end=plan["span"][1],
        n_samples=recording["n_samples"], source_file=recording["source_file"],
        channel=recording["channel"], recording_id=recording["id"],
        data_sha1=sha1, config_hash=config_hash, partial_tail=False,
        elapsed_s=0.0, backfilled=True, out_dir=results_dir,
    )

    run_id = insert_run(conn, config_id, recording["id"],
                        plan["span"][0], plan["span"][1], status="completed")
    insert_artifact(conn, run_id, kind="encoding", path=artifact_path)

    moved_to = None
    if move_original:
        os.makedirs(legacy_dir, exist_ok=True)
        moved_to = os.path.join(legacy_dir, plan["name"])
        shutil.move(plan["path"], moved_to)

    return {"status": "imported", "artifact_path": artifact_path,
            "run_id": run_id, "moved_to": moved_to}


def _parse_assumptions(values):
    """`--assume "file.csv=CH2"` -> {"file.csv": 2}"""
    out = {}
    for item in values or []:
        if "=" not in item:
            raise SystemExit(f"--assume expects FILE=CH<n>, got {item!r}")
        filename, spec = item.split("=", 1)
        spec = spec.strip()
        if not spec.upper().startswith("CH") or not spec[2:].isdigit():
            raise SystemExit(f"--assume expects FILE=CH<n>, got {item!r}")
        out[filename.strip()] = int(spec[2:])
    return out


def main():
    p = argparse.ArgumentParser(
        description="Backfill pre-v1 window-matrix CSVs into the v1 npz format.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--apply", action="store_true",
                   help="Actually write artifacts and move originals (default: report only)")
    p.add_argument("--matrices-dir", default=MATRICES_DIR)
    p.add_argument("--results-dir", default=store.DEFAULT_RESULTS_DIR)
    p.add_argument("--db", default=None, help="Database path (default: the repo default)")
    p.add_argument("--assume", action="append", metavar="FILE=CH<n>",
                   help="Supply a channel a filename cannot carry. Repeatable.")
    p.add_argument("--keep-originals", action="store_true",
                   help="Import without moving the CSVs to MATRICES/_legacy/")
    args = p.parse_args()

    assumptions = _parse_assumptions(args.assume)
    conn = init_db(args.db)

    if not os.path.isdir(args.matrices_dir):
        print(f"No such directory: {args.matrices_dir}")
        return

    csvs = sorted(
        os.path.join(args.matrices_dir, f)
        for f in os.listdir(args.matrices_dir)
        if f.lower().endswith(".csv")
    )
    if not csvs:
        print(f"No CSVs in {args.matrices_dir} — nothing to do.")
        return

    print("=" * 78)
    print(f"  Window-matrix backfill  ({'APPLY' if args.apply else 'REPORT ONLY'})")
    print("=" * 78)

    imported = skipped = already = 0
    for path in csvs:
        name = os.path.basename(path)
        plan = plan_file(conn, path, assume_channel=assumptions.get(name))

        if plan["action"] == "skip":
            skipped += 1
            print(f"\n  SKIP  {name}\n        {plan['reason']}")
            continue

        summary = (
            f"CH{plan['recording']['channel']}  "
            f"WIN{plan['window_min']:g}min  STEP{plan['step_frac']:.0%}  "
            f"{plan['n_windows']:,} windows x {len(plan['columns'])} measures  "
            f"span [{plan['span'][0]:,}, {plan['span'][1]:,})"
        )
        if not args.apply:
            print(f"\n  READY {name}\n        {summary}")
            if plan["dropped_columns"]:
                print(f"        would drop (§2.1): {plan['dropped_columns']}")
            if plan["dropped_non_numeric"]:
                print(f"        would drop (non-numeric): {plan['dropped_non_numeric']}")
            imported += 1
            continue

        result = apply_plan(conn, plan, results_dir=args.results_dir,
                            move_original=not args.keep_originals)
        if result["status"] == "already-imported":
            already += 1
            print(f"\n  HAVE  {name}\n        already registered as run {result['run_id']}")
        else:
            imported += 1
            print(f"\n  OK    {name}\n        {summary}")
            print(f"        -> {result['artifact_path']}  (run {result['run_id']})")
            if result["moved_to"]:
                print(f"        original moved to {result['moved_to']}")

    print("\n" + "-" * 78)
    verb = "would import" if not args.apply else "imported"
    print(f"  {verb}: {imported}   already registered: {already}   skipped: {skipped}")
    if not args.apply:
        print("  Re-run with --apply to write artifacts and move originals.")
    print("=" * 78)


if __name__ == "__main__":
    main()
