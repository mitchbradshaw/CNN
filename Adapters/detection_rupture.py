"""
detection_rupture.py
======================
Adapter for `Working.Detection.rupture.rupture_detect.detect_change_points`.

Output-kind mismatch, resolved per confirmed policy: `detect_change_points`
returns `bkps_idx`, a list of boundary *points*, not `(start, end)`
intervals. Converted here into the segments those points divide the span
into — `[(span_start, bkps[0]), (bkps[0], bkps[1]), ..., (bkps[-1], span_end)]`
— a meaningful, inspectable region per segment, rather than a zero-width
marker. `span_start`/`span_end` are the actual sample bounds of whatever
was passed in (so this works whether `x` is a channel slice or the whole
channel).

Only exposes `penalty` (not `n_bkps`) to keep the parameter spec free of a
cross-parameter mutual-exclusivity constraint the auto-generated UI can't
express; `algo="pelt"` (the default, and the one requiring `penalty`) is
fixed here for that reason. `n_bkps`-driven algorithms can be added as a
second adapter later if wanted.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Detection.rupture.rupture_detect import detect_change_points, plot_change_points
from Working.types import SpanSet


def _run(x, t, fs, cost_model="l2", penalty=50.0, min_size=2, jump=5):
    result = detect_change_points(
        x, t, algo="pelt", cost_model=cost_model, penalty=penalty,
        min_size=min_size, jump=jump,
    )
    bkps = result.bkps_idx.tolist()
    span_start, span_end = 0, len(x)
    bounds = [span_start] + bkps + [span_end]
    intervals = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)
                 if bounds[i + 1] > bounds[i]]
    return AdapterResult(
        output_kind="spanset", intervals=intervals,
        value=SpanSet(
            starts=tuple(s for s, _ in intervals),
            ends=tuple(e for _, e in intervals),
        ),
        meta={"n_bkps": result.n_bkps, "elapsed_s": result.elapsed_s,
              "raw_result": result},
    )


def _plot(x, t, result, cost_model="l2", penalty=50.0, min_size=2, jump=5):
    return plot_change_points(x, t, result.meta["raw_result"])


SPEC = register(AdapterSpec(
    name="detection.rupture",
    display_name="Change-point detection (ruptures / Pelt)",
    stage="detection",
    params=[
        ParamSpec("cost_model", str, "l2", "Cost model", choices=["l1", "l2", "rbf", "normal"]),
        ParamSpec("penalty", float, 50.0, "Segmentation penalty (larger = fewer, coarser segments)", min=1e-6),
        ParamSpec("min_size", int, 2, "Minimum segment length (samples)", min=1),
        ParamSpec("jump", int, 5, "Candidate-breakpoint subsampling stride (samples)", min=1),
    ],
    run=_run,
    input_kind="signal",
    output_kind="spanset",
    plot=_plot,
    description=(
        "Pelt exact change-point detection: partitions the signal into segments "
        "that are statistically distinct under the chosen cost model. Not scale-"
        "invariant — see the module docstring for penalty-tuning guidance."
    ),
))
