"""
build.py
=========
The window-matrix builder, headless and resumable
(WINDOW_MATRIX_UI_PROMPT.md §6.3).

This is the checkpoint/resume logic that used to live in
`Pipelines/window_matrix_build/build_window_matrix.py` with `CH`, `FILENAME`,
`WINSIZE`, `FS` and `STEPFRAC` as module-level constants edited per job —
exactly what `HPC/README.md` says not to do, and the reason the HPC export
goes through `run_recipe.py` rather than invoking a script whose parameters
are source edits.

Two things it does that the old builder did not:

1. **`computed` is a real array, not `~isnan(values)`.** A window whose
   feature function raises is recorded as ATTEMPTED, with NaN as its value.
   The old code could not express that: `_pending` looked for NaN, so a
   window that reliably raised was retried on every resumed job forever, and
   `wm_job.sh` — which decides whether to resubmit by grepping `--status`
   for a partial fraction — would resubmit the chain indefinitely. See
   WINDOW_MATRIX_UI_PROMPT.md §0.2.

2. **No truncated tail windows.** The grid stops at the last start that
   admits a full window (see `create_matrix_at_timescale`), so no column
   contains a value computed on a short slice.

Stage-major, not row-major
--------------------------
Windows are processed stage by stage, matching the old builder and letting
the CNN stage batch its GPU forward passes. A timeout therefore leaves
complete COLUMNS and a partial one, rather than complete rows. Either is
fine for resume because the mask is per-cell; stage-major is chosen because
the alternative would force the CNN stage to run one image at a time.
"""

import logging
import time

import numpy as np

from Working.config import WM_GRAMIAN_MAX_SAMPLES
from Working.database import window_matrix_store as store
from Working.Preprocessing.window_matrix.matrix_calc import create_matrix_at_timescale

log = logging.getLogger("window_matrix.build")

DEFAULT_CNN_MODEL_DIR = "models"
CNN_BATCH_SIZE = 32
# Windows between progress callbacks. Small enough that a UI progress bar
# moves visibly on a slow stage, large enough that the callback is not a
# measurable share of the work on a fast one.
PROGRESS_EVERY = 25


class BuildCancelled(RuntimeError):
    """Cancelled via `should_cancel`. Whatever was computed before the
    cancellation is still returned by the caller — a cancelled build
    produces a partial matrix, not nothing."""


# ---------------------------------------------------------------------------
# Per-stage window functions
# ---------------------------------------------------------------------------

def _catch22_fn():
    from Working.Detection.aeon_features.transformations import catch22_features
    return catch22_features


def _fast_entropy_fn():
    from Working.Detection.analysis.entropy_analysis import (
        _permutation_entropy, _shannon_entropy, _spectral_entropy, _svd_entropy,
    )
    # Order must match store.FAST_ENTROPY_COLUMNS exactly.
    fns = (_shannon_entropy, _spectral_entropy, _svd_entropy, _permutation_entropy)
    return lambda w: np.array([fn(w) for fn in fns], dtype=float)


def _slow_entropy_fn():
    from Working.Detection.analysis.entropy_analysis import (
        _approximate_entropy, _sample_entropy,
    )
    # Order must match store.SLOW_ENTROPY_COLUMNS exactly.
    fns = (_sample_entropy, _approximate_entropy)
    return lambda w: np.array([fn(w) for fn in fns], dtype=float)


_STAGE_FN_FACTORIES = {
    "catch22": _catch22_fn,
    "fast_entropy": _fast_entropy_fn,
    "slow_entropy": _slow_entropy_fn,
}


# ---------------------------------------------------------------------------
# Resume
# ---------------------------------------------------------------------------

def _seed_from_existing(resume_path, columns, start_idx, values, computed):
    """Copy any already-computed cells out of an existing artifact.

    Matched by (start_idx, column name), NOT by position — a resume whose
    stage set or step fraction differs from the original produces a
    different column list and a different grid, and lining those up
    positionally would silently write one measure's values into another's
    column.

    A `backfilled` artifact is refused as a resume source: its mask was
    INFERRED as `~isnan(values)` (see the backfill script), so trusting it
    would reintroduce exactly the NaN-as-sentinel conflation the mask
    exists to remove.
    """
    import os
    if not resume_path or not os.path.isfile(resume_path):
        return 0

    try:
        loaded = store.load_wm(resume_path, mmap=False)
    except Exception as exc:
        log.warning("Could not read resume source %s (%s) — starting fresh.",
                    resume_path, exc)
        return 0

    if bool(loaded.get("backfilled", False)):
        log.warning(
            "Resume source %s is a backfilled artifact: its computed mask was "
            "inferred from NaN, not recorded, so it cannot distinguish 'never "
            "attempted' from 'attempted, NaN'. Starting fresh.", resume_path,
        )
        return 0

    old_cols = {str(c): i for i, c in enumerate(loaded["columns"])}
    old_rows = {int(s): i for i, s in enumerate(loaded["start_idx"])}
    old_values = np.asarray(loaded["values"])
    old_computed = np.asarray(loaded["computed"], dtype=bool)

    copied = 0
    col_pairs = [(j, old_cols[c]) for j, c in enumerate(columns) if c in old_cols]
    for i, start in enumerate(start_idx):
        oi = old_rows.get(int(start))
        if oi is None:
            continue
        for j, oj in col_pairs:
            if old_computed[oi, oj]:
                values[i, j] = old_values[oi, oj]
                computed[i, j] = True
                copied += 1
    log.info("Resumed %d cell(s) from %s", copied, resume_path)
    return copied


# ---------------------------------------------------------------------------
# The builder
# ---------------------------------------------------------------------------

def build_window_matrix(x, fs, window_min, *, step_frac=1.0, stages=None,
                        span_start=0, timeout_s=None, resume_path=None,
                        cnn_model_dir=DEFAULT_CNN_MODEL_DIR, rf_model_path=None,
                        on_progress=None, should_cancel=None, partial_tail=False):
    """Build (or resume) a window matrix over `x`.

    Parameters
    ----------
    x : np.ndarray            the span's signal (already sliced)
    fs : float                sample rate, Hz
    window_min : float        window length, minutes
    step_frac : float         step as a fraction of the window (1.0 = contiguous)
    stages : sequence[str]    subset of `store.ALL_STAGES`; None = all available
    span_start : int          absolute sample index of `x[0]` in the channel —
                              `start_idx` in the result is ABSOLUTE, so a
                              matrix over an offset span still lines up with
                              the channel plot without the reader adding it back
    timeout_s : float         stop cleanly after this many seconds and return
                              a partial result; None = no limit
    resume_path : str         an existing v1 artifact to seed from
    on_progress : callable(done, total, stage)
    should_cancel : callable() -> bool

    Returns
    -------
    dict with `values`, `computed`, `columns`, `start_idx`, `m`, `step`,
    `n_windows`, `stages_run`, `stages_skipped`, `complete`, `elapsed_s`,
    `timed_out`, `cancelled`.

    Stages requested but impossible at this window length (§3.3) appear in
    `stages_skipped` with their columns present and `computed=False`. That
    is not an error: a 600-minute matrix legitimately has no sample entropy
    and no CNN scores, and the artifact must say so rather than omitting the
    columns (which would make two matrices at different scales structurally
    incomparable) or leaving them looking computed.
    """
    t0 = time.time()
    deadline = None if timeout_s in (None, 0) else t0 + float(timeout_s)

    grid = create_matrix_at_timescale(step_frac, x, window_min, fs,
                                      partial_tail=partial_tail)
    m = grid.window_samples
    step = grid.step
    start_idx = np.asarray(grid.df.index.to_numpy(), dtype=np.int64) + int(span_start)
    n_windows = len(start_idx)

    requested = tuple(stages) if stages else store.ALL_STAGES
    available, unavailable = store.stages_available_at(m)
    stages_run = tuple(s for s in requested if s in available)
    stages_skipped = list(s for s in requested if s in unavailable)

    columns = list(store.measure_columns(requested))
    col_index = {c: i for i, c in enumerate(columns)}

    values = np.full((n_windows, len(columns)), np.nan, dtype=np.float32)
    computed = np.zeros(values.shape, dtype=bool)

    if n_windows == 0:
        return _result(values, computed, columns, start_idx, m, step, stages_run,
                       stages_skipped, t0, timed_out=False, cancelled=False)

    _seed_from_existing(resume_path, columns, start_idx, values, computed)

    timed_out = False
    cancelled = False

    for stage in stages_run:
        if timed_out or cancelled:
            break
        cols = list(store.STAGE_COLUMNS[stage]())
        targets = [col_index[c] for c in cols]

        if stage == "cnn":
            timed_out, cancelled = _run_cnn_stage(
                x, start_idx, span_start, m, targets, values, computed,
                cnn_model_dir, deadline, on_progress, should_cancel, n_windows,
            )
            continue
        if stage == "rf":
            timed_out, cancelled = _run_rf_stage(
                x, start_idx, span_start, m, targets, values, computed,
                rf_model_path, deadline, on_progress, should_cancel, n_windows,
            )
            continue

        fn = _STAGE_FN_FACTORIES[stage]()
        timed_out, cancelled = _run_scalar_stage(
            x, start_idx, span_start, m, targets, values, computed,
            fn, stage, deadline, on_progress, should_cancel, n_windows,
        )

    return _result(values, computed, columns, start_idx, m, step, stages_run,
                   stages_skipped, t0, timed_out, cancelled)


def _result(values, computed, columns, start_idx, m, step, stages_run,
            stages_skipped, t0, timed_out, cancelled):
    return {
        "values": values,
        "computed": computed,
        "columns": columns,
        "start_idx": start_idx,
        "m": m,
        "step": step,
        "n_windows": len(start_idx),
        "stages_run": tuple(stages_run),
        "stages_skipped": tuple(stages_skipped),
        # `complete` means every cell was ATTEMPTED — including the cells of
        # a stage that could not run at this window length, which are
        # attempted-and-impossible rather than pending. A matrix whose only
        # uncomputed cells belong to a skipped stage is finished; treating
        # it as partial would make the HPC chain resubmit forever chasing
        # work that can never be done.
        "complete": bool(computed.all()) or _only_skipped_missing(
            computed, columns, stages_skipped),
        "elapsed_s": time.time() - t0,
        "timed_out": timed_out,
        "cancelled": cancelled,
    }


def _only_skipped_missing(computed, columns, stages_skipped):
    """True when every uncomputed cell belongs to a stage that could not run
    at this window length."""
    if not stages_skipped:
        return False
    skipped_cols = set()
    for stage in stages_skipped:
        skipped_cols.update(store.STAGE_COLUMNS[stage]())
    keep = [i for i, c in enumerate(columns) if c not in skipped_cols]
    if not keep:
        return True
    return bool(computed[:, keep].all())


def _progress(on_progress, done, total, stage):
    if on_progress is not None:
        on_progress(done, total, stage)


def _run_scalar_stage(x, start_idx, span_start, m, targets, values, computed,
                      fn, stage, deadline, on_progress, should_cancel, total):
    """Compute one scalar/vector stage window by window.

    A window whose function raises is recorded as ATTEMPTED with NaN — the
    whole point of the mask. The old builder wrote the same NaN but had no
    way to say it was attempted, so it retried the window on every resume.
    """
    pending = np.where(~computed[:, targets].all(axis=1))[0]
    if not len(pending):
        _progress(on_progress, total, total, stage)
        return False, False

    for count, i in enumerate(pending):
        if should_cancel is not None and should_cancel():
            return False, True
        if deadline is not None and time.time() >= deadline:
            log.warning("[%s] timeout after %d/%d windows — returning a partial matrix",
                        stage, count, len(pending))
            return True, False

        window = x[int(start_idx[i]) - int(span_start):
                   int(start_idx[i]) - int(span_start) + m]
        try:
            out = np.atleast_1d(np.asarray(fn(window), dtype=float))
        except Exception as exc:
            log.warning("[%s] window at %d raised %s — recorded as attempted/NaN",
                        stage, start_idx[i], exc)
            out = np.full(len(targets), np.nan)

        if len(out) != len(targets):
            raise ValueError(
                f"[{stage}] returned {len(out)} value(s) for window {start_idx[i]}, "
                f"expected {len(targets)} — the stage's column list and its function "
                "disagree about width."
            )
        for j, target in enumerate(targets):
            values[i, target] = out[j]
            computed[i, target] = True

        if count % PROGRESS_EVERY == 0:
            _progress(on_progress, count, len(pending), stage)

    _progress(on_progress, len(pending), len(pending), stage)
    return False, False


def _run_cnn_stage(x, start_idx, span_start, m, targets, values, computed,
                   model_dir, deadline, on_progress, should_cancel, total):
    """CNN confidence scores, batched per image type.

    A missing model file leaves that image type's column uncomputed and logs
    it — the artifact then honestly reports a partial matrix rather than
    claiming a score it never produced.
    """
    import os
    if m > WM_GRAMIAN_MAX_SAMPLES:
        return False, False

    try:
        import torch
        import torch.nn.functional as F
        from Working.Catalogue.cnn.apply_cnn import load_model, window_to_tensor
        from Working.Catalogue.cnn.cnn_rangapur import get_transforms
    except Exception as exc:
        log.warning("CNN stage unavailable (%s) — columns left uncomputed.", exc)
        return False, False

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")

    for image_type, target in zip(store.CNN_IMAGE_TYPES, targets):
        model_path = os.path.join(model_dir, f"{image_type}_cnn.pth")
        if not os.path.isfile(model_path):
            log.warning("CNN model not found at %s — %s column left uncomputed.",
                        model_path, store.CNN_COLUMNS[list(store.CNN_IMAGE_TYPES).index(image_type)])
            continue

        model = load_model(model_path, device)
        transform = get_transforms(224, is_train=False, is_rgb=(image_type == "fusion"))
        pending = np.where(~computed[:, target])[0]

        for batch_start in range(0, len(pending), CNN_BATCH_SIZE):
            if should_cancel is not None and should_cancel():
                return False, True
            if deadline is not None and time.time() >= deadline:
                return True, False

            batch = pending[batch_start:batch_start + CNN_BATCH_SIZE]
            tensors, valid = [], []
            for i in batch:
                offset = int(start_idx[i]) - int(span_start)
                try:
                    tensors.append(window_to_tensor(x, offset, m, transform, image_type))
                    valid.append(i)
                except Exception as exc:
                    log.warning("[CNN:%s] window at %d failed image generation (%s) — "
                                "recorded as attempted/NaN", image_type, start_idx[i], exc)
                    computed[i, target] = True   # attempted; value stays NaN

            if tensors:
                with torch.no_grad():
                    probs = F.softmax(model(torch.cat(tensors, dim=0).to(device)), dim=1)
                probs = probs.cpu().numpy()
                for i, row in zip(valid, probs):
                    values[i, target] = float(row[0])
                    computed[i, target] = True

            _progress(on_progress, batch_start + len(batch), len(pending), f"cnn:{image_type}")

    return False, False


def _run_rf_stage(x, start_idx, span_start, m, targets, values, computed,
                  model_path, deadline, on_progress, should_cancel, total):
    """Random-forest class probability. `model_path=None` leaves the column
    uncomputed rather than inventing a score."""
    import os
    import sys
    target = targets[0]
    if not model_path or not os.path.isfile(model_path):
        log.info("No random-forest model supplied — rf_p_interesting left uncomputed.")
        return False, False

    try:
        import joblib
        from Working.Catalogue.aeon_classification.classification import ThresholdedPipeline
        sys.modules["__main__"].ThresholdedPipeline = ThresholdedPipeline
        model = joblib.load(model_path)
    except Exception as exc:
        log.warning("Random-forest stage unavailable (%s) — column left uncomputed.", exc)
        return False, False

    pending = np.where(~computed[:, target])[0]
    for batch_start in range(0, len(pending), CNN_BATCH_SIZE):
        if should_cancel is not None and should_cancel():
            return False, True
        if deadline is not None and time.time() >= deadline:
            return True, False

        batch = pending[batch_start:batch_start + CNN_BATCH_SIZE]
        sigs = [x[int(start_idx[i]) - int(span_start):
                  int(start_idx[i]) - int(span_start) + m].reshape(1, -1) for i in batch]
        probas = model.predict_proba(np.stack(sigs).astype(np.float32))
        for i, row in zip(batch, probas):
            values[i, target] = float(row[1])
            computed[i, target] = True
        _progress(on_progress, batch_start + len(batch), len(pending), "rf")

    return False, False
