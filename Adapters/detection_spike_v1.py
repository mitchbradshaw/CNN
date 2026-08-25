"""
detection_spike_v1.py
========================
Adapter for `Working.Detection.analysis.spike_analysis.spike_detection_v1`
(Adamatzky 2023 neighbourhood-average spike detector).

Output-kind mismatch, resolved per confirmed policy: `spike_detection_v1`
returns bare spike sample indices (points), not intervals. Converted here
into the segments between consecutive spikes (inter-spike intervals),
bounded by the span's own start/end — same convention as
`detection_rupture.py`.

Note: `compute_spike_statistics` in the same module is an empty stub (no
body) — not wrapped; nothing to call.
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Detection.analysis.spike_analysis import spike_detection_v1
from Working.types import SpanSet


def _run(x, t, fs, width=20, delta=0.01, d=30):
    spikes = spike_detection_v1(x, width=width, delta=delta, d=d).tolist()
    span_start, span_end = 0, len(x)
    bounds = [span_start] + spikes + [span_end]
    intervals = [(bounds[i], bounds[i + 1]) for i in range(len(bounds) - 1)
                 if bounds[i + 1] > bounds[i]]
    return AdapterResult(
        output_kind="spanset",
        value=SpanSet(
            starts=tuple(s for s, _ in intervals),
            ends=tuple(e for _, e in intervals),
        ),
        meta={"n_spikes": len(spikes), "spike_indices": spikes},
    )


SPEC = register(AdapterSpec(
    name="detection.spike_v1",
    display_name="Spike detection (Adamatzky 2023)",
    stage="detection",
    params=[
        ParamSpec("width", int, 20, "Neighbourhood half-width w (samples)", min=1),
        ParamSpec("delta", float, 0.01, "Detection threshold delta", min=0.0),
        ParamSpec("d", int, 30, "Minimum inter-spike distance (samples)", min=1),
    ],
    run=_run,
    input_kind="signal",
    output_kind="spanset",
    plot=None,
    description=(
        "Neighbourhood-average spike detector with a refractory-period filter. "
        "Output segments are the inter-spike intervals between consecutive "
        "detected spikes."
    ),
))
