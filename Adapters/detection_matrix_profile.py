"""
detection_matrix_profile.py
==============================
Adapter for `Pipelines.matrix_profile.run_matrix_profile.matrix_profile`
(exact, via `stump`/`gpu_stump`) and `matrix_profile_scrump` (anytime
approximate/exact via SCRIMP++), covering the routing tiers described in
MATRIX_PROFILE_UI_PROMPT.md §3.2.

`output_kind='encoding'`: the distance profile `mp` is what gets cached;
motif/discord extraction from `mp` (argmin/argmax, `stumpy.motifs`) is a
separate downstream step, not built as part of this adapter.

`max_span_samples` is derived from the current machine's cost calibration
(`Working.Detection.matrix_profiling.cost`) at *registration* time — see
`cost.max_span_samples_for_background`'s docstring for why this is
computed rather than hardcoded, and why it stays `None` (unbounded) until
a calibration exists.

This adapter also declares `persist` (see `Adapters.base.AdapterSpec`):
when run through `Working.execution.execute_recipe`, its 'encoding' output
is written to disk in the v2 artifact format and registered as an
`artifacts(kind='encoding')` row automatically — no separate UI action or
import step, which is what lets a headless `run_recipe.py` invocation
(e.g. an HPC job, §5) produce a browsable artifact on its own.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.config import MP_MIN_WINDOW_SAMPLES
from Working.Detection.matrix_profiling.cost import max_span_samples_for_background
from Pipelines.matrix_profile.run_matrix_profile import (
    matrix_profile,
    matrix_profile_scrump,
    save_matrix_profile,
)

BACKENDS = ("auto", "stump", "gpu_stump", "scrump")

# Overridable so a test can redirect a real `execute_recipe` run's disk
# output without touching the real `Results/` tree — same pattern as
# `Working.Detection.matrix_profiling.cost.CALIBRATION_PATH`. `_persist`
# below reads this by (module-global) name at call time, so reassigning
# `Adapters.detection_matrix_profile.RESULTS_DIR` in a test takes effect.
RESULTS_DIR = "Results/Detection/matrix_profile"


def _run(x, t, fs, window_min=10.0, backend="auto", scrump_percentage=1.0):
    m = int(round(window_min * 60 * fs))
    if m < MP_MIN_WINDOW_SAMPLES:
        raise ValueError(
            f"window_min={window_min} at fs={fs} gives a {m}-sample window; "
            f"stumpy requires at least {MP_MIN_WINDOW_SAMPLES} samples."
        )
    if m >= len(x):
        raise ValueError(
            f"window (m={m} samples) must be shorter than the span ({len(x)} samples)."
        )

    if backend == "scrump":
        result = matrix_profile_scrump(x, t, m, percentage=scrump_percentage)
    else:
        result = matrix_profile(x, t, m, backend=backend)

    return AdapterResult(
        output_kind="encoding", encoding=result["mp"],
        meta={
            "mpi": result["mpi"], "left_i": result["left_i"], "right_i": result["right_i"],
            "t_mp": result["t_mp"], "m": m, "backend": result["backend"],
            "elapsed_s": result["elapsed_s"], "approx": result["approx"],
            "approx_percentage": result["approx_percentage"],
            "gpu_used": result["backend"] == "gpu_stump",  # back-compat with the old meta key
        },
    )


def _persist(conn, run_id, config_hash, recording, span_start, span_end, params, result):
    from Working.database.matrix_profile_store import compute_data_sha1
    import os

    meta = result.meta
    sha1 = compute_data_sha1(recording["npy_path"]) if os.path.isfile(recording["npy_path"]) else ""
    return save_matrix_profile(
        result.encoding, meta["mpi"], meta["left_i"], meta["right_i"],
        meta["m"], recording["fs"], params["window_min"],
        source_file=recording["source_file"], channel=recording["channel"],
        # n_samples is the length of the SOURCE CHANNEL (MATRIX_PROFILE_UI_PROMPT.md
        # §2.2's table), not this run's span -- span is already on the `runs` row.
        n_samples=recording["n_samples"], data_sha1=sha1,
        backend=meta["backend"], recording_id=recording["id"], config_hash=config_hash,
        approx=meta["approx"], approx_percentage=meta["approx_percentage"],
        elapsed_s=meta["elapsed_s"], out_dir=RESULTS_DIR,
    )


SPEC = register(AdapterSpec(
    name="detection.matrix_profile",
    display_name="Matrix profile (STUMPY)",
    stage="detection",
    params=[
        ParamSpec("window_min", float, 10.0, "Motif window length (minutes)", min=0.001),
        ParamSpec("backend", str, "auto", "Computation backend", choices=list(BACKENDS)),
        ParamSpec("scrump_percentage", float, 1.0,
                  "SCRIMP++ fraction to compute (backend='scrump' only); 1.0 converges to exact",
                  min=0.0, max=1.0),
    ],
    run=_run,
    output_kind="encoding",
    plot=None,
    max_span_samples=max_span_samples_for_background(),
    persist=_persist,
    description=(
        "Distance profile via STUMPY (auto: gpu_stump with CPU stump fallback; "
        "or force stump/gpu_stump/scrump). Finding motifs/discords from the "
        "profile is a separate downstream step."
    ),
))
