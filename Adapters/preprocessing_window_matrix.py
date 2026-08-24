"""
preprocessing_window_matrix.py
================================
Adapter for `Working.Preprocessing.window_matrix.build.build_window_matrix`
— the window matrix as a normal recipe step, so the Run panel builds its
controls automatically and the HPC path goes through `run_recipe.py` rather
than a script with per-job source edits (WINDOW_MATRIX_UI_PROMPT.md §6.3).

`output_kind='windowset'`: the per-window feature matrix rides as attached
features on a `WindowSet`, with no timepoint alignment (CODING_STANDARDS
3.2 — a per-window feature table is not `Scores`). It is what gets cached.
Dendrogram clustering over the matrix is a separate downstream step, not
part of this adapter.

`persist` is declared (see `Adapters.base.AdapterSpec`), so a headless
`run_recipe.py` invocation writes the v1 `.npz` and registers an
`artifacts(kind='encoding')` row on its own — no separate import step, which
is what lets the ladder and the coverage ribbons pick up a cluster run's
output the moment the file comes back.

Resume
------
`resume_path` is a normal recipe parameter, and it is DELIBERATELY set from
the very first export rather than being filled in on the second job: the
artifact path is deterministic from (source stem, channel, window_min,
step_frac), so passing it up front keeps the recipe — and therefore the
config hash — identical across every job in a resubmit chain. A path added
only on resumption would make job 2 a different recipe from job 1, and the
chain would build two half-matrices instead of one whole one.

`execute_recipe` short-circuits on a completed run for the same recipe and
span, so a resuming job must pass `--force`; the generated chain script does.

Progress
--------
`on_progress`/`should_cancel` are plain keyword args on `_run`, not
`ParamSpec` params — they're execution-time callables, not recipe state, so
they must never enter the config hash. `Working.execution.execute_recipe`
forwards them from its own `run_kwargs=` argument (checked against `_run`'s
signature, so every other adapter is unaffected) — see that function's
docstring for why this is a second, finer-grained progress channel from its
own per-STEP `on_progress`, not the same one reused.
"""

import os

import numpy as np
import pandas as pd

from Adapters.base import AdapterResult, AdapterSpec, ParamSpec
from Adapters.registry import register
from Working.config import WM_MIN_WINDOW_SAMPLES, WM_MIN_WINDOWS
from Working.database import window_matrix_store as store
from Working.types import WindowSet
from Working.Preprocessing.window_matrix.build import (
    DEFAULT_CNN_MODEL_DIR, build_window_matrix,
)
from Working.Preprocessing.window_matrix.cost import max_span_samples_for_background

# Overridable so a test can redirect a real `execute_recipe` run's disk
# output without touching the real `Results/` tree — same pattern as
# `Adapters.detection_matrix_profile.RESULTS_DIR`. `_persist` reads this by
# module-global name at call time, so reassigning it in a test takes effect.
RESULTS_DIR = store.DEFAULT_RESULTS_DIR


def _selected_stages(catch22, fast_entropy, slow_entropy, cnn, rf):
    """Boolean params -> the stage tuple, in canonical order.

    Five checkboxes rather than one comma-separated string because
    `AdapterSpec.params` auto-generates the UI control from the type: five
    bools give five checkboxes with tooltips, a string gives a free-text box
    that can be misspelt into a silent no-op.
    """
    flags = {"catch22": catch22, "fast_entropy": fast_entropy,
             "slow_entropy": slow_entropy, "cnn": cnn, "rf": rf}
    return tuple(s for s in store.ALL_STAGES if flags[s])


def _run(x, t, fs, window_min=10.0, step_frac=1.0, catch22=True,
         fast_entropy=True, slow_entropy=True, cnn=False, rf=False,
         timeout_s=0.0, resume_path="", cnn_model_dir=DEFAULT_CNN_MODEL_DIR,
         rf_model_path="", partial_tail=False, on_progress=None, should_cancel=None):
    m = int(round(window_min * 60 * fs))
    if m < WM_MIN_WINDOW_SAMPLES:
        raise ValueError(
            f"window_min={window_min} at fs={fs} gives a {m}-sample window; the "
            f"measures need at least {WM_MIN_WINDOW_SAMPLES} samples to be defined. "
            "This is a floor on meaning, not on the call succeeding — a periodogram "
            f"over {m} samples has {max(m // 2, 1)} bin(s)."
        )
    if m > len(x):
        raise ValueError(
            f"window (m={m} samples) is longer than the span ({len(x)} samples) — "
            "no window fits."
        )

    stages = _selected_stages(catch22, fast_entropy, slow_entropy, cnn, rf)
    if not stages:
        raise ValueError("No stages selected — a window matrix with no measures is empty.")

    step = store.step_samples(m, step_frac)
    n_windows = store.n_windows_for(len(x), m, step, partial_tail=partial_tail)
    if n_windows < WM_MIN_WINDOWS:
        raise ValueError(
            f"a {m:,}-sample window over a {len(x):,}-sample span yields {n_windows} "
            f"window(s); below {WM_MIN_WINDOWS} there is no matrix, just a few rows."
        )

    # `t` is `np.arange(span_start, span_end) / fs` (see
    # `Working.execution._load_signal`), so this recovers the span's absolute
    # offset — which is what makes `start_idx` absolute in the channel and
    # therefore directly overlayable on the channel plot.
    span_start = int(round(float(t[0]) * fs)) if len(t) else 0

    built = build_window_matrix(
        x, fs, window_min, step_frac=step_frac, stages=stages,
        span_start=span_start, timeout_s=(timeout_s or None),
        resume_path=(resume_path or None), cnn_model_dir=cnn_model_dir,
        rf_model_path=(rf_model_path or None), partial_tail=partial_tail,
        on_progress=on_progress, should_cancel=should_cancel,
    )

    features = pd.DataFrame(built["values"], columns=list(built["columns"]))
    window_set = WindowSet(starts=built["start_idx"], length=m, fs=fs, features=features)

    return AdapterResult(
        output_kind="windowset",
        value=window_set,
        meta={k: v for k, v in built.items() if k != "values"},
    )


def _persist(conn, run_id, config_hash, recording, span_start, span_end, params, result):
    from Working.database.matrix_profile_store import compute_data_sha1

    meta = result.meta
    sha1 = (compute_data_sha1(recording["npy_path"])
            if os.path.isfile(recording["npy_path"]) else "")

    return store.save_wm(
        result.value.features.to_numpy(), meta["computed"], meta["columns"], meta["start_idx"],
        m=meta["m"], step=meta["step"], fs=recording["fs"],
        window_min=params["window_min"], step_frac=params["step_frac"],
        span_start=span_start, span_end=span_end,
        # n_samples is the length of the SOURCE CHANNEL, not this run's span —
        # the span is already on the `runs` row. Same call the matrix-profile
        # adapter makes.
        n_samples=recording["n_samples"],
        source_file=recording["source_file"], channel=recording["channel"],
        recording_id=recording["id"], data_sha1=sha1, config_hash=config_hash,
        partial_tail=meta.get("partial_tail", params.get("partial_tail", False)),
        elapsed_s=meta["elapsed_s"], out_dir=RESULTS_DIR,
    )


def default_artifact_path(recording, window_min, step_frac=1.0, out_dir=None):
    """The path `persist` will write for this (recording, geometry).

    Deterministic, and exposed so a caller can put it in `resume_path`
    BEFORE the first run — see the module docstring for why the resume path
    has to be in the recipe from the start rather than added on the second
    job.
    """
    stem = os.path.splitext(recording["source_file"])[0]
    name = store.artifact_name(stem, recording["channel"], window_min, step_frac)
    return os.path.join(out_dir or RESULTS_DIR, f"{name}.npz")


SPEC = register(AdapterSpec(
    name="preprocessing.window_matrix",
    display_name="Window matrix (per-window measures)",
    stage="preprocessing",
    params=[
        ParamSpec("window_min", float, 10.0,
                  "Window length in minutes. One of the ladder timescales "
                  "(1 / 10 / 60 / 600) unless you specifically want a custom scale — "
                  "off-ladder matrices are stored and usable but are not browsable in "
                  "the timescale switcher.", min=0.001),
        ParamSpec("step_frac", float, 1.0,
                  "Step between windows as a fraction of the window length. "
                  "1.0 = contiguous non-overlapping; 0.5 = 50 % overlap.",
                  min=0.001, max=1.0),
        ParamSpec("catch22", bool, True, "22 Catch22 summary statistics (~m log m per window)"),
        ParamSpec("fast_entropy", bool, True,
                  "Shannon, spectral, SVD and permutation entropy (~m log m per window)"),
        ParamSpec("slow_entropy", bool, True,
                  "Sample and approximate entropy. O(m^2) PER WINDOW — unavailable "
                  "above a 4096-sample window, where it stops being slow and becomes "
                  "infeasible."),
        ParamSpec("cnn", bool, False,
                  "CNN confidence scores for the four Gramian image types. Needs the "
                  "model files; the Gramian image is m x m, so unavailable above a "
                  "5000-sample window."),
        ParamSpec("rf", bool, False,
                  "Random-forest class probability. Needs rf_model_path."),
        ParamSpec("timeout_s", float, 0.0,
                  "Stop cleanly after this many seconds and store a PARTIAL matrix "
                  "that a later run resumes from. 0 = no limit. Set this a few "
                  "minutes below an HPC job's --time so the job saves before SLURM "
                  "kills it.", min=0.0),
        ParamSpec("resume_path", str, "",
                  "An existing v1 artifact to seed already-computed cells from. "
                  "Deterministic (see default_artifact_path) and set from the FIRST "
                  "export, so every job in a resubmit chain shares one recipe hash."),
        ParamSpec("cnn_model_dir", str, DEFAULT_CNN_MODEL_DIR,
                  "Directory holding {fusion,GASF,GADF,recurrence}_cnn.pth"),
        ParamSpec("rf_model_path", str, "",
                  "Path to a saved Catch22+RandomForest joblib pipeline"),
        ParamSpec("partial_tail", bool, False,
                  "Include trailing windows shorter than the full window length. "
                  "Off by default: a feature computed on a truncated window looks "
                  "comparable to the rest of its column and is not."),
    ],
    run=_run,
    output_kind="windowset",
    plot=None,
    # Derived from this machine's calibration at REGISTRATION time, so the
    # headless path cannot be handed a job the UI would have refused. None
    # (unbounded) while uncalibrated — a guessed cap would refuse legitimate
    # work, which is a worse failure than allowing a slow run.
    max_span_samples=max_span_samples_for_background(),
    persist=_persist,
    description=(
        "Per-window single-value measures (Catch22, entropy, optional CNN/RF "
        "scores) over a fixed timescale grid. Stored as a v1 .npz with a "
        "per-cell computed mask, so a timed-out build resumes exactly where it "
        "stopped and a window whose measure legitimately returns NaN is never "
        "retried. Dendrogram clustering over the matrix is a separate step."
    ),
))
