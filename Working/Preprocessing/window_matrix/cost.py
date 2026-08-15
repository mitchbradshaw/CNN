"""
cost.py
========
Per-machine cost calibration and routing-tier estimation for window-matrix
builds (WINDOW_MATRIX_UI_PROMPT.md §6).

Different shape from the matrix profile's cost model
-----------------------------------------------------
`Working/Detection/matrix_profiling/cost.py` gets away with ONE constant per
backend because `stump` is O(n^2) in series length and effectively flat in
the window length `m`. A window-matrix build is the opposite: **linear in
the number of windows, strongly super-linear in `m` per window**, with the
exponent differing by stage.

    t_est = n_windows * sum over enabled stages of  k_stage * shape_stage(m)

    shape:
      catch22        m log m
      fast_entropy   m log m      (shannon, spectral, svd, permutation)
      slow_entropy   m^2          (sample, approximate)
      cnn            m^2          (Gramian image construction; the 224x224
                                   forward pass itself is ~constant in m)
      rf             m            (one predict_proba over the raw window)

So `k` is fitted PER STAGE, and — unlike the MP module — from TWO window
lengths rather than one, specifically so a wrong exponent shows up as a bad
fit instead of being silently absorbed into `k`. `fit_ratio` in each
calibration entry is the ratio of the two implied constants; far from 1.0
means the shape above does not describe this machine's behaviour and the
estimate should not be trusted.

Like the MP module, this never falls back to a hardcoded constant.
`estimate_seconds` returns `None` when any requested stage is uncalibrated —
a wrong estimate here routes a multi-hour job into the "wait with a spinner"
path, and "not calibrated" with a Calibrate button is the honest answer.
"""

import datetime
import json
import multiprocessing
import os
import tempfile
import time

import numpy as np

from Working.config import (
    WM_BACKGROUND_BUDGET_S,
    WM_GRAMIAN_MAX_SAMPLES,
    WM_INTERACTIVE_BUDGET_S,
    WM_SLOW_ENTROPY_MAX_SAMPLES,
)

CALIBRATION_PATH = os.path.join("DATA", "db", "wm_calibration.json")

# Two window lengths, both short enough that even the O(m^2) stages finish
# in well under a second per window, and far enough apart (16x) that the
# fitted exponent is actually tested.
CALIBRATION_M = (256, 4096)

# Stages calibrated by this module. "cnn" is deliberately absent: its cost
# is dominated by a GPU forward pass through a model that may not exist on
# the machine doing the calibrating, and timing it against a missing or
# different model would produce a confidently wrong number. It is handled
# by `CNN_UNCALIBRATED_MESSAGE` below instead.
CALIBRATABLE_STAGES = ("catch22", "fast_entropy", "slow_entropy", "rf")

CNN_UNCALIBRATED_MESSAGE = (
    "CNN stages are not cost-calibrated: their cost depends on the model file "
    "and the GPU actually present at run time. Estimates that include the CNN "
    "stage are reported as unknown rather than guessed."
)


def _shape(stage, m):
    """The complexity shape for one stage at window length `m`, in arbitrary
    units. `k_stage` converts these to seconds per window."""
    m = float(m)
    if stage in ("catch22", "fast_entropy"):
        return m * np.log2(max(m, 2.0))
    if stage in ("slow_entropy", "cnn"):
        return m * m
    if stage == "rf":
        return m
    raise ValueError(f"Unknown stage {stage!r}")


# ---------------------------------------------------------------------------
# Calibration file
# ---------------------------------------------------------------------------

def _calibration_key():
    """Calibration is per (cpu_count, numpy version, aeon version). Any of
    those changing invalidates a prior calibration rather than silently
    reusing a stale constant — same contract as the MP module's key."""
    try:
        import aeon
        aeon_version = str(getattr(aeon, "__version__", "unknown"))
    except Exception:
        aeon_version = "absent"
    return json.dumps({
        "cpu_count": multiprocessing.cpu_count(),
        "numpy_version": np.__version__,
        "aeon_version": aeon_version,
    }, sort_keys=True)


def _load_calibration():
    if not os.path.isfile(CALIBRATION_PATH):
        return {}
    with open(CALIBRATION_PATH, "r") as f:
        return json.load(f)


# Retry budget for the atomic rename in `_save_calibration` — see the comment
# there. Short and bounded: this guards a microsecond-wide window, not a
# genuinely locked file.
_REPLACE_ATTEMPTS = 5
_REPLACE_BACKOFF_S = 0.05

def _save_calibration(data):
    """Write the calibration file atomically.

    A plain `open(path, "w")` truncates first and writes second, so any reader
    that arrives between those two steps — another process, a background
    thread, or a test that shares the path — sees a partial file and fails
    with a `JSONDecodeError`. Writing to a sibling temp file and renaming it
    over the target makes the swap a single filesystem operation: a reader
    sees either the whole old file or the whole new one, never a fragment.

    `os.replace` is atomic on NTFS and POSIX alike, and unlike `os.rename` it
    overwrites an existing destination on Windows.
    """
    directory = os.path.dirname(CALIBRATION_PATH) or "."
    os.makedirs(directory, exist_ok=True)

    # A FIXED temp name (`path + ".tmp"`) is not enough: this module is written
    # from a UI background worker as well as the main thread, so two writers
    # would open the same temp file, and on Windows the second `os.replace`
    # fails with WinError 5 because the first still holds a handle. `mkstemp`
    # gives each writer its own file in the destination directory, so the only
    # contended operation is the rename itself.
    fd, tmp_path = tempfile.mkstemp(
        dir=directory,
        prefix=os.path.basename(CALIBRATION_PATH) + ".",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, indent=2, sort_keys=True)
            f.flush()
            os.fsync(f.fileno())
        # `os.replace` can still raise PermissionError on Windows if a reader,
        # an indexer or a virus scanner holds the destination open at that
        # instant. That window is microseconds; retry briefly rather than
        # failing a calibration over it.
        for attempt in range(_REPLACE_ATTEMPTS):
            try:
                os.replace(tmp_path, CALIBRATION_PATH)
                return
            except PermissionError:
                if attempt == _REPLACE_ATTEMPTS - 1:
                    raise
                time.sleep(_REPLACE_BACKOFF_S * (attempt + 1))
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Timing one stage
# ---------------------------------------------------------------------------

def _stage_callable(stage):
    """The function whose per-window cost defines this stage, imported
    lazily so an absent optional dependency disables only its own stage."""
    if stage == "catch22":
        from Working.Detection.aeon_features.transformations import catch22_features
        return catch22_features
    if stage == "fast_entropy":
        from Working.Detection.analysis.entropy_analysis import (
            _permutation_entropy, _shannon_entropy, _spectral_entropy, _svd_entropy,
        )
        fns = (_shannon_entropy, _spectral_entropy, _svd_entropy, _permutation_entropy)
        return lambda w: [fn(w) for fn in fns]
    if stage == "slow_entropy":
        from Working.Detection.analysis.entropy_analysis import (
            _approximate_entropy, _sample_entropy,
        )
        fns = (_sample_entropy, _approximate_entropy)
        return lambda w: [fn(w) for fn in fns]
    if stage == "rf":
        # No model is loaded here — the cost that scales with m is the
        # window handling, not the tree traversal (which is O(depth) and
        # independent of m). A rough linear constant is enough: RF is never
        # the stage that decides a routing tier.
        return lambda w: float(np.dot(w, w))
    raise ValueError(f"Stage {stage!r} is not calibratable; known: {CALIBRATABLE_STAGES}")


def _time_stage(fn, m, repeats=3, seed=0):
    """Median wall-clock seconds for one call of `fn` on an m-sample window."""
    rng = np.random.default_rng(seed)
    window = rng.standard_normal(m).astype(np.float64)
    fn(window)  # warm up: first call pays import/JIT costs that do not recur
    times = []
    for _ in range(repeats):
        t0 = time.perf_counter()
        fn(window)
        times.append(time.perf_counter() - t0)
    return float(np.median(times))


def calibrate(stages=CALIBRATABLE_STAGES, force=False, m_values=CALIBRATION_M):
    """Time each stage at two window lengths, fit `k_stage`, and write the
    result to `DATA/db/wm_calibration.json` keyed by the current machine
    signature.

    Returns `{stage: entry}` where `entry` carries `k`, the two raw timings,
    and `fit_ratio` — the ratio of the constants the two measurements imply.
    A `fit_ratio` far from 1.0 means the assumed complexity shape does not
    describe this machine and the estimate should be treated as unreliable
    rather than merely imprecise.

    Stages whose dependency is missing are recorded with `k=None` and an
    `error` string rather than being silently omitted, so `estimate_seconds`
    can distinguish "never calibrated" from "cannot be calibrated here".
    """
    key = _calibration_key()
    data = _load_calibration()
    existing = data.get(key, {})

    m_lo, m_hi = sorted(m_values)
    out = {}
    for stage in stages:
        if not force and stage in existing and existing[stage].get("k") is not None:
            out[stage] = existing[stage]
            continue
        try:
            fn = _stage_callable(stage)
            t_lo = _time_stage(fn, m_lo)
            t_hi = _time_stage(fn, m_hi)
        except Exception as exc:
            out[stage] = {"k": None, "error": f"{type(exc).__name__}: {exc}"}
            continue

        k_lo = t_lo / _shape(stage, m_lo)
        k_hi = t_hi / _shape(stage, m_hi)
        # Geometric mean: the two measurements are equally trusted, and a
        # geometric mean is the right average for a multiplicative constant.
        k = float(np.sqrt(max(k_lo, 1e-30) * max(k_hi, 1e-30)))
        out[stage] = {
            "k": k,
            "m_lo": m_lo, "m_hi": m_hi,
            "t_lo": t_lo, "t_hi": t_hi,
            "fit_ratio": float(k_hi / k_lo) if k_lo > 0 else None,
            "calibrated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }

    existing.update(out)
    data[key] = existing
    _save_calibration(data)
    return out


def calibration_status(stages=CALIBRATABLE_STAGES):
    """`{stage: "ok" | "uncalibrated" | "unavailable"}` for this machine —
    what a Calibrate button renders next to each stage."""
    entries = _load_calibration().get(_calibration_key(), {})
    status = {}
    for stage in stages:
        entry = entries.get(stage)
        if entry is None:
            status[stage] = "uncalibrated"
        elif entry.get("k") is None:
            status[stage] = "unavailable"
        else:
            status[stage] = "ok"
    return status


# ---------------------------------------------------------------------------
# Estimation
# ---------------------------------------------------------------------------

def estimate_seconds(n_windows, m, stages):
    """Estimated wall-clock seconds to build `n_windows` windows of `m`
    samples for `stages` on this machine.

    Returns `None` — never a guess — when any requested stage has no usable
    calibration on this machine. `"cnn"` is always in that category (see
    `CNN_UNCALIBRATED_MESSAGE`), so an estimate covering a CNN stage is
    always unknown; the caller should estimate the CPU stages alone and say
    the CNN stage is unbudgeted, rather than showing a number that silently
    omits the most expensive part.
    """
    entries = _load_calibration().get(_calibration_key(), {})
    total = 0.0
    for stage in stages:
        entry = entries.get(stage)
        if entry is None or entry.get("k") is None:
            return None
        total += entry["k"] * _shape(stage, m)
    return total * float(n_windows)


def routing_tier(seconds):
    """'interactive' | 'background' | 'hpc' from an estimated-seconds value,
    or 'unknown' if `seconds` is None (uncalibrated)."""
    if seconds is None:
        return "unknown"
    if seconds <= WM_INTERACTIVE_BUDGET_S:
        return "interactive"
    if seconds <= WM_BACKGROUND_BUDGET_S:
        return "background"
    return "hpc"


def max_span_samples_for_background(window_min=10.0, fs=1.0, step_frac=1.0,
                                    stages=CALIBRATABLE_STAGES):
    """The span length at which a build of this geometry would hit
    `WM_BACKGROUND_BUDGET_S` — the adapter's declared `max_span_samples`, so
    the headless path cannot be handed a job the UI would have refused.

    `None` if uncalibrated, meaning "no guard" (unbounded) rather than a
    guessed cap: a wrong cap here would refuse legitimate work, which is a
    worse failure than allowing a slow run.

    Note this is geometry-specific by nature — cost per SAMPLE of span falls
    as the window grows, because a longer window means proportionally fewer
    of them. The default arguments describe the repo's most common build
    (10-minute non-overlapping windows at fs=1); the adapter recomputes it
    for the geometry actually requested when it can.
    """
    m = int(round(window_min * 60 * fs))
    step = max(1, int(np.floor(step_frac * m)))
    per_window = estimate_seconds(1, m, stages)
    if per_window is None or per_window <= 0:
        return None
    max_windows = WM_BACKGROUND_BUDGET_S / per_window
    return int(m + max(0.0, max_windows - 1) * step)


def describe(n_windows, m, stages):
    """A dict a UI can render directly without re-deriving anything:
    per-stage seconds, total, tier, and which stages could not be budgeted.

    Splitting "estimated" from "unbudgeted" is the point. A build that
    includes the CNN stage has a real, knowable CPU cost and an unknown GPU
    cost; collapsing that to a single `None` hides useful information, and
    collapsing it to a single number hides the risk.
    """
    entries = _load_calibration().get(_calibration_key(), {})
    per_stage, unbudgeted = {}, []
    for stage in stages:
        entry = entries.get(stage)
        if entry is None or entry.get("k") is None:
            unbudgeted.append(stage)
            continue
        per_stage[stage] = entry["k"] * _shape(stage, m) * float(n_windows)

    total = sum(per_stage.values()) if per_stage else None
    return {
        "per_stage_seconds": per_stage,
        "estimated_seconds": total,
        "unbudgeted_stages": unbudgeted,
        # A tier is only meaningful when EVERY stage is budgeted; otherwise
        # the number it would be derived from is a lower bound, not an
        # estimate, and routing on a lower bound is how a long job ends up
        # in the interactive path.
        "tier": routing_tier(total) if not unbudgeted else "unknown",
        "n_windows": int(n_windows),
        "m": int(m),
        "notes": [CNN_UNCALIBRATED_MESSAGE] if "cnn" in unbudgeted else [],
    }


def stage_limits():
    """The hard per-stage window-length limits, for a UI that wants to
    explain why a stage is greyed out at a given timescale. These are
    availability limits, not cost limits — above them the stage cannot run
    at all (WINDOW_MATRIX_UI_PROMPT.md §3.3)."""
    return {
        "slow_entropy": WM_SLOW_ENTROPY_MAX_SAMPLES,
        "cnn": WM_GRAMIAN_MAX_SAMPLES,
    }
