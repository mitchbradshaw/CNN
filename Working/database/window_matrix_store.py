"""
window_matrix_store.py
=======================
Storage format and headless query layer for window matrices
(WINDOW_MATRIX_UI_PROMPT.md §3) — deliberately shaped like
`matrix_profile_store.py` so the two read as siblings, and using the same
`configs`/`runs`/`artifacts` tables rather than adding any of its own.

A stored window matrix is already expressible in the schema: a `configs`
row (recipe = one `preprocessing.window_matrix` step with `window_min=S`,
`step_frac=F`), a `runs` row with `status='completed'` and the span, and an
`artifacts` row of `kind='encoding'`. `find_completed_run`
(`Working.database.runs`) is the underlying reuse lookup this module builds
on; the functions here add the window-matrix-specific view on top: "what
timescales exist for this recording", "which regions of the channel are
already covered", "is this artifact stale", "load the v1 npz".

The `computed` mask
-------------------
The single most important thing this format does that the CSV files in
`MATRICES/` did not: it stores, alongside the values, a boolean mask saying
whether each cell was ever ATTEMPTED. The old builder used NaN to mean both
"not yet computed" and "computed, and the answer is NaN", so a window whose
feature function reliably raised was retried on every resumed job forever —
and `HPC/Preprocessing/wm_job.sh`, which decides whether to resubmit itself
by grepping for a partial fraction in `--status` output, would resubmit the
chain indefinitely. See WINDOW_MATRIX_UI_PROMPT.md §0.2.

Resume logic must read `computed`. It must never read `np.isnan(values)`.
"""

import datetime
import json
import os

import numpy as np

from Working.config import (
    WM_GRAMIAN_MAX_SAMPLES,
    WM_MIN_WINDOW_SAMPLES,
    WM_MIN_WINDOWS,
    WM_SCALE_LADDER_MIN,
    WM_SLOW_ENTROPY_MAX_SAMPLES,
)
from Working.database.matrix_profile_store import compute_data_sha1
from Working.database.queries import get_recording_by_id, merge_intervals

# Bumped when the on-disk key set changes in a way a reader must notice.
ARTIFACT_VERSION = 1

DEFAULT_RESULTS_DIR = os.path.join("Results", "Preprocessing", "window_matrix")

_ISCLOSE_RTOL = 1e-6


# ===========================================================================
# The measure set (WINDOW_MATRIX_UI_PROMPT.md §2)
# ===========================================================================
#
# Column names are kept EXACTLY as the pre-v1 CSVs spell them, spaces in the
# entropy names included, so the backfill is a pure re-serialisation and
# existing analysis code keeps working. They are ugly; renaming them is a
# separate decision with its own migration, not something to do quietly
# inside a storage change.

FAST_ENTROPY_COLUMNS = (
    "shannon entropy",
    "spectral entropy",
    "svd entropy",
    "permutation entropy",
)
SLOW_ENTROPY_COLUMNS = (
    "sample entropy",
    "approximate entropy",
)
CNN_IMAGE_TYPES = ("fusion", "GASF", "GADF", "recurrence")
CNN_COLUMNS = tuple(f"cnn_p_{img}_interesting" for img in CNN_IMAGE_TYPES)
RF_COLUMNS = ("rf_p_interesting",)


def catch22_columns():
    """The 22 Catch22 column names, imported lazily so this module stays
    importable without `aeon` installed — a UI listing stored matrices
    should not need the feature-extraction stack present."""
    from Working.Detection.aeon_features.transformations import CATCH22_FEATURE_NAMES
    return tuple(f"catch22_{name}" for name in CATCH22_FEATURE_NAMES)


# Stage name -> the columns it produces. The stage is the unit of cost
# estimation (§6.1), of resume, and of per-scale availability (§3.3) — a
# stage is available at a scale or it is not; individual columns within one
# never diverge.
STAGE_COLUMNS = {
    "catch22": catch22_columns,
    "fast_entropy": lambda: FAST_ENTROPY_COLUMNS,
    "slow_entropy": lambda: SLOW_ENTROPY_COLUMNS,
    "cnn": lambda: CNN_COLUMNS,
    "rf": lambda: RF_COLUMNS,
}
ALL_STAGES = ("catch22", "fast_entropy", "slow_entropy", "cnn", "rf")


def measure_columns(stages=ALL_STAGES):
    """Full ordered column list for `stages`, in the canonical group order
    (Catch22, fast entropy, slow entropy, CNN, RF)."""
    unknown = set(stages) - set(STAGE_COLUMNS)
    if unknown:
        raise ValueError(f"Unknown stage(s) {sorted(unknown)}; known: {ALL_STAGES}")
    out = []
    for stage in ALL_STAGES:
        if stage in stages:
            out.extend(STAGE_COLUMNS[stage]())
    return tuple(out)


def stages_available_at(m):
    """`(available, unavailable)` stage tuples for a window of `m` samples.

    This is the window matrix's analogue of the matrix profile's `invalid`
    state, and it is finer-grained: an MP scale is valid or it is not,
    whereas a WM scale can be perfectly fine for Catch22 and entropy while
    being genuinely impossible for the O(m^2) stages.

    - Sample/approximate entropy are O(m^2) PER WINDOW. At m=600 (10 min at
      fs=1) they already dominate; at m=36000 (600 min) they are 1.3e9
      operations per window.
    - The Gramian images behind the CNN scores are O(m^2) in MEMORY — a GASF
      image is an m x m matrix before the resize to 224x224, so m=36000 is
      ~5 TB.

    Above those limits the stage is UNAVAILABLE at that scale: not slow, not
    failed. Its columns are written with `computed=False` and the UI names
    which groups were excluded rather than offering a Compute button that
    would OOM.
    """
    available, unavailable = [], []
    for stage in ALL_STAGES:
        if stage == "slow_entropy" and m > WM_SLOW_ENTROPY_MAX_SAMPLES:
            unavailable.append(stage)
        elif stage == "cnn" and m > WM_GRAMIAN_MAX_SAMPLES:
            unavailable.append(stage)
        else:
            available.append(stage)
    return tuple(available), tuple(unavailable)


def unavailable_reason(stage, m):
    """Human-readable explanation for why `stage` cannot run at window
    length `m`, or None if it can."""
    if stage == "slow_entropy" and m > WM_SLOW_ENTROPY_MAX_SAMPLES:
        return (f"sample/approximate entropy are O(m^2) per window; m={m:,} exceeds "
                f"the {WM_SLOW_ENTROPY_MAX_SAMPLES:,}-sample limit.")
    if stage == "cnn" and m > WM_GRAMIAN_MAX_SAMPLES:
        return (f"the Gramian image behind each CNN score is an m x m matrix; "
                f"m={m:,} exceeds the {WM_GRAMIAN_MAX_SAMPLES:,}-sample limit.")
    return None


# ===========================================================================
# Grid geometry
# ===========================================================================

def window_samples(window_min, fs):
    """Window length in samples for a ladder entry at this sample rate.
    `m` is always DERIVED — `WM_SCALE_LADDER_MIN` is in minutes precisely so
    the same ladder means the same thing at fs=0.25 and fs=1."""
    return int(round(window_min * 60 * fs))


def step_samples(m, step_frac):
    """Step between consecutive window starts, in samples."""
    return max(1, int(np.floor(step_frac * m)))


def n_windows_for(span_len, m, step, partial_tail=False):
    """Number of windows a grid of this geometry yields over `span_len`
    samples. Matches `create_matrix_at_timescale` exactly — including its
    default of stopping at the last start that admits a FULL window."""
    stop = span_len if partial_tail else span_len - m + 1
    if stop <= 0:
        return 0
    return int(np.ceil(stop / step))


# ===========================================================================
# The v1 artifact
# ===========================================================================

def artifact_name(source_stem, channel, window_min, step_frac):
    """Canonical filename stem. Unlike the pre-v1 CSVs, every field needed
    to identify a matrix is present and consistently encoded — the old names
    variously omitted the channel entirely
    (`M2_concat_fs1_10min_27118wins_consecutive.csv`), encoded the window
    count instead of the geometry, or carried `.mat` inside a `.csv` name."""
    return (f"wm_v{ARTIFACT_VERSION}_{source_stem}_CH{channel}"
            f"_WIN{window_min:g}min_STEP{int(round(step_frac * 100)):d}pct")


def save_wm(values, computed, columns, start_idx, *, m, step, fs, window_min,
            step_frac, span_start, span_end, n_samples, source_file, channel,
            recording_id, data_sha1, config_hash, partial_tail=False,
            elapsed_s=0.0, backfilled=False, out_dir=DEFAULT_RESULTS_DIR,
            builder_version=ARTIFACT_VERSION):
    """Write a v1 window-matrix artifact and return its path.

    `values` is (n_windows, n_features) float32; `computed` is a bool array
    of the same shape. They are validated against each other and against
    `columns` / `start_idx` here rather than at read time — a mismatched
    artifact is easy to write and miserable to debug three steps later.
    """
    values = np.asarray(values, dtype=np.float32)
    computed = np.asarray(computed, dtype=bool)
    columns = np.asarray(list(columns), dtype="<U64")
    start_idx = np.asarray(start_idx, dtype=np.int64)

    if values.ndim != 2:
        raise ValueError(f"values must be 2-D (n_windows, n_features), got {values.shape}")
    if computed.shape != values.shape:
        raise ValueError(
            f"computed mask shape {computed.shape} does not match values {values.shape}. "
            "The mask is what distinguishes 'never attempted' from 'attempted, NaN' "
            "(WINDOW_MATRIX_UI_PROMPT.md §0.2) — it cannot be approximated."
        )
    if len(columns) != values.shape[1]:
        raise ValueError(f"{len(columns)} column name(s) for {values.shape[1]} column(s)")
    if len(start_idx) != values.shape[0]:
        raise ValueError(f"{len(start_idx)} start index/indices for {values.shape[0]} row(s)")

    os.makedirs(out_dir, exist_ok=True)
    stem = artifact_name(os.path.splitext(source_file)[0], channel, window_min, step_frac)
    path = os.path.join(out_dir, f"{stem}.npz")

    np.savez_compressed(
        path,
        values=values,
        computed=computed,
        columns=columns,
        start_idx=start_idx,
        m=np.int32(m),
        step=np.int32(step),
        fs=np.float32(fs),
        window_min=np.float32(window_min),
        step_frac=np.float32(step_frac),
        span_start=np.int64(span_start),
        span_end=np.int64(span_end),
        n_samples=np.int64(n_samples),
        partial_tail=np.bool_(partial_tail),
        complete=np.bool_(bool(computed.all())),
        backfilled=np.bool_(backfilled),
        source_file=str(source_file),
        channel=np.int32(channel),
        recording_id=np.int64(recording_id),
        data_sha1=str(data_sha1),
        config_hash=str(config_hash),
        builder_version=np.int32(builder_version),
        created_at=str(datetime.datetime.now(datetime.timezone.utc).isoformat()),
        elapsed_s=np.float32(elapsed_s),
    )
    return path


def _load_npz_meta(artifact_path):
    """Read only the small scalar fields out of a v1 npz — never touches
    `values`/`computed`, so this stays cheap when listing many artifacts."""
    with np.load(artifact_path, allow_pickle=False) as data:
        return {
            "window_min": float(data["window_min"]),
            "step_frac": float(data["step_frac"]),
            "m": int(data["m"]),
            "step": int(data["step"]),
            "fs": float(data["fs"]),
            "span_start": int(data["span_start"]),
            "span_end": int(data["span_end"]),
            "n_windows": int(data["start_idx"].shape[0]),
            "columns": [str(c) for c in data["columns"]],
            "complete": bool(data["complete"]),
            "partial_tail": bool(data["partial_tail"]),
            "backfilled": bool(data["backfilled"]) if "backfilled" in data.files else False,
            "created_at": str(data["created_at"]),
            "elapsed_s": float(data["elapsed_s"]),
            "data_sha1": str(data["data_sha1"]),
            "config_hash": str(data["config_hash"]),
        }


def load_wm(artifact_path, *, mmap=True):
    """Load a v1 artifact as a plain dict of arrays/scalars.

    `mmap=True` (default) attempts `mmap_mode='r'`. `savez_compressed`
    archives cannot actually be memory-mapped (numpy raises), so this
    transparently falls back to a normal in-memory load — which is the
    normal case for this repo's artifacts, and cheap: the real matrix is
    27,118 x 33 float32, under 4 MB.
    """
    if mmap:
        try:
            with np.load(artifact_path, mmap_mode="r", allow_pickle=False) as data:
                return {key: data[key] for key in data.files}
        except Exception:
            pass
    with np.load(artifact_path, allow_pickle=False) as data:
        return {key: data[key] for key in data.files}


def to_dataframe(loaded, *, include_uncomputed=False):
    """A `start_idx`-indexed DataFrame, NaN wherever `computed` is False.

    This is the bridge to everything downstream: `preprocess_window_matrix`
    takes a DataFrame, so the dendrogram pipeline consumes the new format
    with no changes. A stage that was unavailable at this scale (§3.3) is
    100 % NaN and gets dropped by that pipeline's own
    `_remove_all_nan_columns`, which is the correct outcome.

    `include_uncomputed=True` returns the raw stored values instead, mask
    ignored — for inspecting what a partial artifact physically contains,
    not for analysis.
    """
    import pandas as pd

    values = np.asarray(loaded["values"], dtype=np.float64)
    if not include_uncomputed:
        values = np.where(np.asarray(loaded["computed"], dtype=bool), values, np.nan)
    return pd.DataFrame(
        values,
        index=pd.Index(np.asarray(loaded["start_idx"], dtype=np.int64), name="start_idx"),
        columns=[str(c) for c in loaded["columns"]],
    )


# ===========================================================================
# The registry view over configs/runs/artifacts
# ===========================================================================

def _window_matrix_config_ids(conn):
    """(config_id, window_min, step_frac) for every config whose recipe is
    exactly one `preprocessing.window_matrix` step.

    Recipes with a preceding preprocessing step (detrend, bandpass, ...) are
    deliberately NOT matched: a window matrix over a detrended signal is a
    different quantity from one over the raw trace, and silently listing it
    under the same timescale would be the same category error as reusing an
    approximate matrix profile where an exact one was asked for.
    """
    out = []
    for row in conn.execute("SELECT id, config_json FROM configs"):
        try:
            recipe = json.loads(row["config_json"])
        except (TypeError, ValueError):
            continue
        steps = recipe.get("steps") or []
        if len(steps) != 1:
            continue
        step = steps[0]
        if step.get("stage") != "preprocessing" or step.get("algorithm") != "window_matrix":
            continue
        params = step.get("params") or {}
        window_min = params.get("window_min")
        if window_min is None:
            continue
        out.append((row["id"], float(window_min), float(params.get("step_frac", 1.0))))
    return out


def list_wm_runs(conn, recording_id, *, include_partial=True):
    """One dict per stored window matrix for this recording.

    Keys: window_min, step_frac, m, step, n_windows, columns, complete,
    partial_tail, backfilled, span, run_id, artifact_path, created_at,
    elapsed_s, stale.

    `stale` = the artifact's `data_sha1` no longer matches the current
    source `.npy`. Stale rows are always included (never hidden) so the
    caller can grey them out with a recompute action — same contract as
    `matrix_profile_store.list_mp_runs`.
    """
    recording = get_recording_by_id(conn, recording_id)
    current_sha1 = None
    if recording is not None and os.path.isfile(recording["npy_path"]):
        current_sha1 = compute_data_sha1(recording["npy_path"])

    out = []
    for config_id, _window_min, _step_frac in _window_matrix_config_ids(conn):
        runs = conn.execute(
            """SELECT * FROM runs WHERE config_id = ? AND recording_id = ?
               AND status = 'completed' ORDER BY id DESC""",
            (config_id, recording_id),
        ).fetchall()
        for run in runs:
            artifacts = conn.execute(
                "SELECT * FROM artifacts WHERE run_id = ? AND kind = 'encoding' "
                "ORDER BY created_at DESC LIMIT 1",
                (run["id"],),
            ).fetchall()
            if not artifacts:
                continue
            artifact = artifacts[0]
            try:
                meta = _load_npz_meta(artifact["path"])
            except (FileNotFoundError, OSError, KeyError, ValueError):
                continue
            if not include_partial and not meta["complete"]:
                continue
            entry = dict(meta)
            entry.update(
                run_id=run["id"],
                artifact_path=artifact["path"],
                span=(int(run["span_start"]), int(run["span_end"])),
                stale=current_sha1 is not None and meta["data_sha1"] != current_sha1,
            )
            out.append(entry)
    return out


def find_wm(conn, recording_id, window_min, *, step_frac=1.0, span=None,
            require_complete=False):
    """The best available stored matrix for (recording, window_min,
    step_frac[, span]).

    Preference order: fresh+complete, then fresh+partial, then stale. A
    stale or partial result is still returned WITH its flags set, never
    silently dropped and never silently substituted for a complete one —
    `require_complete=True` skips partial artifacts entirely, so a
    half-built matrix can never stand in where a full one was requested.

    Returns None on a total miss.
    """
    candidates = [
        r for r in list_wm_runs(conn, recording_id, include_partial=not require_complete)
        if np.isclose(r["window_min"], window_min, rtol=_ISCLOSE_RTOL)
        and np.isclose(r["step_frac"], step_frac, rtol=_ISCLOSE_RTOL)
    ]
    if span is not None:
        candidates = [r for r in candidates if tuple(r["span"]) == (int(span[0]), int(span[1]))]
    if require_complete:
        candidates = [r for r in candidates if r["complete"]]
    if not candidates:
        return None

    fresh = [r for r in candidates if not r["stale"]]
    fresh_complete = [r for r in fresh if r["complete"]]
    if fresh_complete:
        return fresh_complete[0]
    if fresh:
        return fresh[0]
    return candidates[0]


def ladder_status(conn, recording_id, fs, n_samples, *, step_frac=1.0,
                  span=None, estimate=None):
    """One row per `WM_SCALE_LADDER_MIN` entry — what the timescale switcher
    renders directly.

    `state` is one of:

    - "available"  — a fresh, complete artifact exists.
    - "partial"    — a fresh artifact exists but not every cell is computed;
                     offer Resume, and report how far it got.
    - "stale"      — an artifact exists but the source `.npy` has changed.
    - "missing"    — never computed; offer a Compute button.
    - "invalid"    — this timescale cannot exist for this span/fs at all —
                     explain why, no Compute button.

    Note "available" does NOT imply all 33 measures: `available_stages` /
    `unavailable_stages` carry the per-scale availability from §3.3, and a
    perfectly good matrix at 600 minutes legitimately has neither the slow
    entropies nor the CNN scores. The UI must show that rather than letting
    "available" imply completeness it does not have.

    `estimate` is an optional `callable(n_windows, m, stages) -> seconds or
    None`, normally `Working.Preprocessing.window_matrix.cost.estimate_seconds`
    — injected rather than imported so this module stays importable without
    the cost/calibration machinery present.
    """
    span_start, span_end = (0, n_samples) if span is None else (int(span[0]), int(span[1]))
    span_len = span_end - span_start
    runs = list_wm_runs(conn, recording_id, include_partial=True)

    out = []
    for window_min in WM_SCALE_LADDER_MIN:
        m = window_samples(window_min, fs)
        step = step_samples(m, step_frac)
        available, unavailable = stages_available_at(m)
        row = {
            "window_min": window_min,
            "m": m,
            "step": step,
            "available_stages": available,
            "unavailable_stages": unavailable,
            "unavailable_reasons": {s: unavailable_reason(s, m) for s in unavailable},
        }

        if m < WM_MIN_WINDOW_SAMPLES:
            row.update(
                state="invalid",
                reason=(f"window is {m} sample(s) at fs={fs:g}; the measures need at "
                        f"least {WM_MIN_WINDOW_SAMPLES} to be defined (a periodogram "
                        f"over {m} samples has {max(m // 2, 1)} bin(s))."),
                n_windows=0, est_seconds=None, run_id=None, artifact_path=None,
            )
            out.append(row)
            continue

        n_win = n_windows_for(span_len, m, step)
        row["n_windows"] = n_win

        if n_win < WM_MIN_WINDOWS:
            row.update(
                state="invalid",
                reason=(f"a {m:,}-sample window over a {span_len:,}-sample span yields "
                        f"{n_win} window(s); below {WM_MIN_WINDOWS} there is no matrix, "
                        "just a few rows."),
                est_seconds=None, run_id=None, artifact_path=None,
            )
            out.append(row)
            continue

        est = estimate(n_win, m, available) if estimate is not None else None
        row["est_seconds"] = est

        matching = [
            r for r in runs
            if np.isclose(r["window_min"], window_min, rtol=_ISCLOSE_RTOL)
            and np.isclose(r["step_frac"], step_frac, rtol=_ISCLOSE_RTOL)
        ]
        fresh = [r for r in matching if not r["stale"]]
        fresh_complete = [r for r in fresh if r["complete"]]

        if fresh_complete:
            best = fresh_complete[0]
            row.update(state="available", reason=None, est_seconds=None,
                       run_id=best["run_id"], artifact_path=best["artifact_path"])
        elif fresh:
            best = fresh[0]
            row.update(state="partial",
                       reason="artifact exists but not every cell has been computed.",
                       run_id=best["run_id"], artifact_path=best["artifact_path"])
        elif matching:
            best = matching[0]
            row.update(state="stale",
                       reason="source data changed since this artifact was computed.",
                       run_id=best["run_id"], artifact_path=best["artifact_path"])
        else:
            row.update(state="missing", reason=None, run_id=None, artifact_path=None)
        out.append(row)
    return out


def coverage_for_span(conn, recording_id, span=None, *, step_frac=1.0,
                      include_stale=False):
    """`{window_min: [(start, end), ...]}` — the regions of the channel
    already covered by a stored matrix, per ladder timescale.

    This is what backs the coverage ribbons: "if a user has a plot in the
    run algorithm section and the window-matrix preprocessing step is
    selected, it should be visible which regions of the plot already have
    pre-computed window matrices, and at what scales."

    Intervals are merged through `queries.merge_intervals` — the SAME
    function `reviewed_fraction` and `UI.plots.build_reviewed_ribbon` use —
    so a timescale covered by three overlapping runs reports one interval,
    not three, and the coverage ribbon can never disagree with a coverage
    percentage computed elsewhere.

    Only ladder timescales appear. Off-ladder matrices are still stored and
    still usable via the adapter's own `window_min`, but they are not
    browsable here, for the same reason `MATRIX_PROFILE_UI_PROMPT.md` §1
    excludes off-ladder MP windows: the ladder exists to make scales
    comparable across channels and recordings.

    Stale artifacts are EXCLUDED by default. A region whose source data has
    changed is not covered in any useful sense, and showing it as covered
    would be misleading in the worst direction.
    """
    runs = list_wm_runs(conn, recording_id, include_partial=True)
    clip = None if span is None else (int(span[0]), int(span[1]))

    coverage = {}
    for window_min in WM_SCALE_LADDER_MIN:
        matches = _matching_wm_spans(runs, window_min, step_frac,
                                     include_stale=include_stale, clip=clip)
        spans = [(s, e) for _r, s, e in matches]
        if spans:
            coverage[window_min] = merge_intervals(spans)
    return coverage


def _matching_wm_spans(runs, window_min, step_frac, *, include_stale, clip):
    """`(run, clipped_start, clipped_end)` for every run in `runs` that
    matches `(window_min, step_frac)`, isn't stale (unless `include_stale`),
    and still has positive length after clipping to `clip`. Shared by
    `coverage_for_span` and `coverage_by_completeness` so the matching rules
    can't drift apart between the two."""
    out = []
    for r in runs:
        if not np.isclose(r["window_min"], window_min, rtol=_ISCLOSE_RTOL):
            continue
        if not np.isclose(r["step_frac"], step_frac, rtol=_ISCLOSE_RTOL):
            continue
        if r["stale"] and not include_stale:
            continue
        start, end = r["span"]
        if clip is not None:
            start, end = max(start, clip[0]), min(end, clip[1])
            if end <= start:
                continue
        out.append((r, start, end))
    return out


def coverage_by_completeness(conn, recording_id, span=None, *, step_frac=1.0,
                             include_stale=False):
    """Like `coverage_for_span`, but splits each scale's coverage into
    `{"complete": [...], "partial": [...]}` merged-interval lists.

    A window matrix's `complete` flag (WINDOW_MATRIX_UI_PROMPT.md §3.4) means
    every cell was attempted — not that the run is somehow "more present"
    spatially. So a bucket covered by a `complete` run and one covered by a
    `partial` run are both genuinely covered; the coverage RIBBON just needs
    to render them in different colours (§4, §8.3), the same full/partial/gap
    treatment `UI.plots.build_reviewed_ribbon` already gives reviewed
    coverage. This is a separate function rather than a parameter on
    `coverage_for_span` because most callers (e.g. "is there anything at
    this scale at all") don't care about the split and shouldn't have to
    unpack a nested dict to find out.
    """
    runs = list_wm_runs(conn, recording_id, include_partial=True)
    clip = None if span is None else (int(span[0]), int(span[1]))

    coverage = {}
    for window_min in WM_SCALE_LADDER_MIN:
        matches = _matching_wm_spans(runs, window_min, step_frac,
                                     include_stale=include_stale, clip=clip)
        complete = [(s, e) for r, s, e in matches if r["complete"]]
        partial = [(s, e) for r, s, e in matches if not r["complete"]]
        entry = {}
        if complete:
            entry["complete"] = merge_intervals(complete)
        if partial:
            entry["partial"] = merge_intervals(partial)
        if entry:
            coverage[window_min] = entry
    return coverage
