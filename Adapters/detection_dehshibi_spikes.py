"""
detection_dehshibi_spikes.py
==============================
Adapter for `Working.Detection.analysis.dehshibi_detection_analysis.detect_spikes`
(Dehshibi & Adamatzky 2021 full spike-detection pipeline).

Good native fit: `detect_spikes` already returns `(spikes, pseudo_spikes, info)`
with `spikes`/`pseudo_spikes` as `(start, end)` tuples — real intervals, no
point-to-segment conversion needed (unlike `detection_rupture.py` /
`detection_spike_v1.py`).

Only the parameters a user would plausibly want to tune are exposed
(`n_p`, `min_spike_duration`, `min_roi_wavelet`, `epsilon_factor`); the
Morse-wavelet constants (`beta`, `gamma`, `eta`) are paper-fixed and left
at their defaults rather than cluttering the auto-generated form with
physics internals nobody adjusts in practice.

This pipeline is the most compute-heavy adapter in this set (Morse wavelet
transform + envelope extraction per histogram-sliced chunk) — exactly the
kind of step whose per-step duration (recorded by `execute_recipe`) is
meant to surface "this belongs on the cluster, not interactively".
"""

from Adapters.base import AdapterSpec, AdapterResult, ParamSpec
from Adapters.registry import register
from Working.Detection.analysis.dehshibi_detection_analysis import (
    detect_spikes,
    plot_spike_detection,
)
from Working.types import SpanSet


def _run(x, t, fs, n_p=60, min_spike_duration=60, min_roi_wavelet=30, epsilon_factor=0.05):
    spikes, pseudo_spikes, info = detect_spikes(
        x, fs=fs, n_p=n_p, min_spike_duration=min_spike_duration,
        min_roi_wavelet=min_roi_wavelet, epsilon_factor=epsilon_factor,
    )
    return AdapterResult(
        output_kind="spanset",
        value=SpanSet(
            starts=tuple(s for s, _ in spikes),
            ends=tuple(e for _, e in spikes),
        ),
        meta={"pseudo_spikes": pseudo_spikes, "n_spikes": len(spikes),
              "n_pseudo_spikes": len(pseudo_spikes), "n_chunks": len(info["chunks"])},
    )


def _plot(x, t, result, n_p=60, min_spike_duration=60, min_roi_wavelet=30, epsilon_factor=0.05):
    # `plot_spike_detection` wants the legacy [(start, end), ...] shape; the
    # SpanSet holds the same spans as parallel tuples, so rebuild the pairs
    # here rather than teach a plotting helper the type system.
    spans = list(zip(result.value.starts, result.value.ends))
    return plot_spike_detection(x, spans, result.meta["pseudo_spikes"], fs=1.0)


SPEC = register(AdapterSpec(
    name="detection.dehshibi_spikes",
    display_name="Spike detection (Dehshibi & Adamatzky 2021)",
    stage="detection",
    params=[
        ParamSpec("n_p", int, 60, "Minimum extrema separation (samples)", min=1),
        ParamSpec("min_spike_duration", int, 60, "Minimum confirmed-spike length (samples)", min=1),
        ParamSpec("min_roi_wavelet", int, 30, "Minimum wavelet-ROI length (samples)", min=1),
        ParamSpec("epsilon_factor", float, 0.05, "Candidate-region prominence threshold (fraction of range)", min=0.0, max=1.0),
    ],
    run=_run,
    input_kind="signal",
    output_kind="spanset",
    plot=_plot,
    description=(
        "Full Morse-wavelet + analytic-envelope spike detection pipeline "
        "(BioSystems 2021). Slow relative to the other detectors here — a "
        "good candidate for checking per-step duration before running on a "
        "long span."
    ),
))
