"""
probe12.py
===========
The scale probe. What window length can the detector actually frame these
events at - measured, before the production run, and reported before
anything is detected in anger.

What the probe varies, and the one thing it had to add
------------------------------------------------------
The work order specifies one axis: three trial sub-windows per region, at
5%, 50% and 95% through it, each 2e5 samples, run at three candidate WINDOW
LENGTHS spanning two orders of magnitude. That arm is `WINDOW_SAMPLES` and
it is run exactly as specified.

A second arm, `DECIMATION_FACTORS`, varies the SAMPLING RATE instead. It is
here because the first arm alone cannot answer the question the first arm
was asked. A window length sets how much signal the autocorrelation derives
its scale from; it does not change how many samples an event's fall is made
of, and on this recording that is the binding quantity:

    CH3, region A.  The visible drops fall about 12 mV over about 1300
    samples - 0.0092 mV per sample - against a per-sample noise of
    0.055 mV. THE FALL DESCENDS AT 0.17 OF THE PER-SAMPLE NOISE. The trace
    is nowhere monotonically descending at the sample level, and
    `detect.find_trough` walks the per-sample gradient, so it ends every
    fall within a few samples of the steepest one no matter how long the
    window is.

For contrast, the Reishi corpus this chain was built on: 0.4 mV over 7
samples is 0.057 mV per sample against a Fig2A noise of 0.0017-0.0066 mV,
so its falls descend at 10-30x the per-sample noise. The two corpora are on
opposite sides of the ratio that decides whether the detector can see an
event at all, and that is a property of the sampling rate against the event
duration, not of the window.

Both arms are reported. The window arm is the answer to the question as
asked; the decimation arm is the evidence for what to do about it.

Cost is a probe result too
--------------------------
A 2e5-sample window at 10 Hz on CH3 did not complete in 35 minutes on this
machine. That is not an aside - region A is 12.6e6 samples, so a production
run at any window the first arm would choose is out of reach, and a probe
that silently hung would have reported that as "still working". Every cell
runs under `TIMEOUT_S` in its own process and a timeout is recorded as a
result with its own row.

The profile says where it goes: `detect5.significant_rises`, called from
`window_bounds`, called from `tighten_window` inside `run_sensitive`'s
autotune - 52 s of 128 s on a 50,000-sample window, over 19,775 calls. The
cost is in the number of encoded rises, which on a long noisy window is
enormous, and it grows faster than the window does.

No plotting library.
"""

import json
import multiprocessing as mp
import os
import tempfile
import time

import numpy as np

from Pipelines.drop_motifs import corpora10, lionsmane12, passes9

# Three trial sub-windows per region, as fractions of the way through it.
SUB_WINDOW_FRACTIONS = (0.05, 0.50, 0.95)
SUB_WINDOW_SAMPLES = 200_000

# Arm 1: candidate window lengths, spanning two orders of magnitude and
# bounded above by the sub-window itself.
WINDOW_SAMPLES = (2_000, 20_000, 200_000)

# Arm 2: candidate sampling rates, as decimation factors from 10 Hz.
# 1 is the native rate and is included so the two arms share a row.
DECIMATION_FACTORS = (1, 5, 10, 25, 50, 100)

# Per-cell wall clock, and it is a MEASUREMENT BUDGET rather than a guess
# at how long the machine needs. A cell runs the detector over 2e5 samples;
# region A is 12.6e6, i.e. 63 times more, with more windows at any window
# length the first arm would choose. A cell that cannot finish 2e5 samples
# inside two minutes puts the production run beyond a day, so two minutes is
# already past the point where the answer changes.
TIMEOUT_S = 120.0

OVERLAP = passes9.DEFAULT_OVERLAP

# The production window is this multiple of the median measured fall,
# clamped, then rounded to a round number of minutes or hours.
WINDOW_FALL_MULTIPLE = 100.0
WINDOW_MULTIPLE_MIN = 30.0
WINDOW_MULTIPLE_MAX = 200.0


def per_sample_noise_mv(x):
    """Standard deviation of the first difference, in millivolts.

    Deliberately NOT `floor10.amplitude_sigma_mv`, which is a robust
    second-difference estimator and answers a different question. What is
    wanted here is "how far does the trace move between two samples", to
    be compared against how far a real fall moves between two samples.
    """
    return float(np.std(np.diff(np.asarray(x, dtype=float))) * 1000.0)


def _describe(rows, fs):
    """The fall-duration and depth distributions one cell found."""
    if not rows:
        return {"n": 0}
    falls = np.array([abs(float(r["fall_duration_s"])) for r in rows])
    depths = np.array([abs(float(r["drop_depth_mv"])) for r in rows])
    samples = np.array([max(1, int(r["trough_idx"]) - int(r["onset_idx"]))
                        for r in rows])
    q = lambda a: [float(v) for v in np.percentile(a, [10, 50, 90])]
    return {
        "n": len(rows),
        "fall_s_p10_p50_p90": q(falls),
        "depth_mv_p10_p50_p90": q(depths),
        "samples_in_fall_p10_p50_p90": q(samples),
        "median_fall_s": float(np.median(falls)),
        "median_samples_in_fall": float(np.median(samples)),
        "median_depth_mv": float(np.median(depths)),
        "max_depth_mv": float(depths.max()),
    }


def _cell_worker(payload, result_path):
    """One probe cell, in its own process so a timeout can kill it.

    The result goes to a FILE, not to a `multiprocessing.Queue`. A Queue
    looks like the obvious channel and deadlocks here: a child that has put
    an object on a Queue does not exit until the parent has drained it, so
    `Process.join(timeout)` can block past its own timeout, and terminating
    a child mid-put leaves the parent's `get()` waiting on a pipe nobody
    will write to. Measured before it was changed: cells ran 20 minutes
    against a 420 s timeout that never fired. A file has neither failure -
    the child writes and exits, and the parent reads only after the join
    has returned, or not at all.
    """
    try:
        rows, _arrays, info = passes9.detect_sliding(
            payload["x"], payload["fs"],
            catalogue_id=payload["catalogue_id"],
            recording_id=lionsmane12.RECORDING_ID,
            source_file=lionsmane12.SOURCE_FILE, channel=payload["channel"],
            window_s=payload["window_s"], overlap=OVERLAP,
            span_label=payload["label"], span_key=payload["key"],
            max_passes=3, fine=True, sensitive=True, micro=True)
        result = {"ok": True, "n_windows": info["n_windows"],
                  "n_before_dedup": info["n_before_dedup"],
                  **_describe(rows, payload["fs"])}
    except Exception as exc:                                  # noqa: BLE001
        result = {"ok": False, "error": repr(exc)}
    with open(result_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle)


def run_cell(x, fs, *, window_s, channel, catalogue_id, label, key,
             timeout_s=TIMEOUT_S):
    """One (sub-window, candidate) cell, bounded in wall clock.

    A cell that does not finish is a RESULT and is recorded as one. See the
    module docstring: this is the measurement that says the production run
    at 10 Hz is out of reach, and it only exists because the probe refuses
    to wait forever.
    """
    payload = dict(x=np.asarray(x, dtype=float), fs=float(fs),
                   window_s=float(window_s), channel=int(channel),
                   catalogue_id=int(catalogue_id), label=label, key=key)
    handle, result_path = tempfile.mkstemp(prefix="probe12_", suffix=".json")
    os.close(handle)
    # "spawn" explicitly rather than by platform default, so the same code
    # path runs everywhere and a fork-only assumption cannot creep in.
    context = mp.get_context("spawn")
    process = context.Process(target=_cell_worker, args=(payload, result_path))
    started = time.time()
    process.start()
    process.join(timeout_s)
    try:
        if process.is_alive():
            process.kill()
            process.join(30)
            return {"ok": False, "timed_out": True,
                    "seconds": round(time.time() - started, 1),
                    "error": f"did not complete within {timeout_s:g} s"}
        elapsed = round(time.time() - started, 1)
        try:
            with open(result_path, encoding="utf-8") as reader:
                result = json.load(reader)
        except (OSError, ValueError):
            result = {"ok": False,
                      "error": f"worker exited {process.exitcode} with no result"}
        result["seconds"] = elapsed
        result["timed_out"] = False
        return result
    finally:
        try:
            os.unlink(result_path)
        except OSError:
            pass


def sub_windows(region, fractions=SUB_WINDOW_FRACTIONS,
                length=SUB_WINDOW_SAMPLES):
    """`[(fraction, start, stop), ...]` - the trial sub-windows of a region.

    Clipped so a sub-window at 95% still lies wholly inside the region;
    otherwise the last trial is short and its scale is derived from less
    signal than the others, which is the one thing the probe must not vary
    by accident.
    """
    region = lionsmane12.REGIONS[region] if isinstance(region, str) else region
    out = []
    for fraction in fractions:
        start = region.start + int(round(fraction * (region.n_samples - length)))
        start = int(np.clip(start, region.start, region.stop - length))
        out.append((float(fraction), start, start + int(length)))
    return out


def probe_region(region, *, window_samples=WINDOW_SAMPLES,
                 decimation_factors=DECIMATION_FACTORS,
                 timeout_s=TIMEOUT_S, log=print):
    """Both arms, over one region's three trial sub-windows."""
    region = lionsmane12.REGIONS[region] if isinstance(region, str) else region
    cells = []

    for fraction, start, stop in sub_windows(region):
        x = lionsmane12.load_channel(region.channel, start, stop)
        noise = per_sample_noise_mv(x)
        common = dict(region=region.key, channel=region.channel,
                      fraction=fraction, sub_start_idx=start,
                      sub_stop_idx=stop,
                      per_sample_noise_mv=noise)
        log(f"  {region.label} @{fraction:.0%} samples {start}-{stop}  "
            f"per-sample noise {noise:.4f} mV")

        for width in window_samples:
            if width > (stop - start):
                continue
            result = run_cell(
                x, lionsmane12.FS, window_s=width / lionsmane12.FS,
                channel=region.channel, catalogue_id=region.catalogue_id,
                label=region.label, key=region.key_stem, timeout_s=timeout_s)
            cell = dict(arm="window", window_samples=int(width),
                        window_s=width / lionsmane12.FS,
                        fs=lionsmane12.FS, decimation=1, **common, **result)
            cells.append(cell)
            log(f"    window {width:>7} samples "
                f"({width / lionsmane12.FS:>8.0f} s): {_line(cell)}")

        for factor in decimation_factors:
            if factor == 1:
                continue
            y, fs = corpora10.decimate_to(x, lionsmane12.FS, factor=factor)
            # The window is held at the SAME SECONDS across the arm, which
            # is `corpora10`'s own rule for the rate control: everything
            # about the framing is fixed and only the samples per event
            # change.
            width_s = (stop - start) / lionsmane12.FS
            result = run_cell(
                y, fs, window_s=width_s, channel=region.channel,
                catalogue_id=region.catalogue_id, label=region.label,
                key=region.key_stem, timeout_s=timeout_s)
            cell = dict(arm="rate", window_samples=int(len(y)),
                        window_s=width_s, fs=float(fs), decimation=int(factor),
                        per_sample_noise_decimated_mv=per_sample_noise_mv(y),
                        **common, **result)
            cells.append(cell)
            log(f"    decimate x{factor:<4} (fs {fs:g} Hz): {_line(cell)}")

    return cells


def _line(cell):
    if cell.get("timed_out"):
        return f"DID NOT COMPLETE in {cell['seconds']:g} s"
    if not cell.get("ok"):
        return f"ERROR {cell.get('error')}"
    if not cell.get("n"):
        return f"0 events  ({cell['seconds']}s)"
    return (f"{cell['n']:>5} events  median fall "
            f"{cell['median_fall_s']:>8.2f} s "
            f"({cell['median_samples_in_fall']:.0f} samples)  "
            f"median depth {cell['median_depth_mv']:.3f} mV  "
            f"max {cell['max_depth_mv']:.2f} mV  ({cell['seconds']}s)")


def choose_window(cells, *, multiple=WINDOW_FALL_MULTIPLE,
                  lo=WINDOW_MULTIPLE_MIN, hi=WINDOW_MULTIPLE_MAX):
    """The production window from the WINDOW arm's measured falls.

    `multiple` x the median measured fall, clamped between `lo` and `hi` x
    it, then rounded to a round number of minutes or hours. Returns the
    arithmetic AND the inputs, so the number on the report can be checked
    without re-running the probe.

    This is the rule the work order specifies. Whether its input is a
    measurement of the events or a measurement of the noise is a separate
    question, and `verdict` is where that is answered.
    """
    window_arm = [c for c in cells if c.get("arm") == "window"]
    usable = [c for c in window_arm if c.get("ok") and c.get("n")]
    if not usable:
        # "Found nothing" and "never finished" are different answers and the
        # work order acts on them differently: the first says the events are
        # not there, the second says the measurement is out of reach. Saying
        # "found no events" about a cell that was killed at its time limit
        # would be a false statement about the recording.
        timed_out = sum(1 for c in window_arm if c.get("timed_out"))
        return {
            "chosen_s": None,
            "n_cells": len(window_arm),
            "n_cells_timed_out": timed_out,
            "reason": (
                f"{timed_out} of {len(window_arm)} window-arm cells did not "
                "complete inside their time limit; the rest found no events. "
                "This is a cost result, not a statement that the region is "
                "empty."
                if timed_out else
                "the window arm found no events at any candidate length"),
        }
    falls = np.array([c["median_fall_s"] for c in usable], dtype=float)
    median_fall = float(np.median(falls))
    target = multiple * median_fall
    window_s = float(np.clip(target, lo * median_fall, hi * median_fall))
    return {
        "median_measured_fall_s": median_fall,
        "multiple": multiple,
        "target_s": target,
        "clamped_s": window_s,
        "chosen_s": _round_to_round_number(window_s),
        "n_cells": len(usable),
        "per_cell_median_fall_s": [float(f) for f in falls],
    }


def _round_to_round_number(seconds):
    """To a round number of minutes below an hour, of hours above it."""
    seconds = float(seconds)
    if seconds < 60:
        return float(max(1, round(seconds)))
    if seconds < 3600:
        return float(round(seconds / 60.0) * 60)
    return float(round(seconds / 3600.0) * 3600)


DEPTH_AGREEMENT = 3.0


def verdict(cells, region):
    """Does the window arm measure the region's events, or its noise?

    The probe's own consistency check, and the reason the run stops rather
    than proceeding.

    THE COMPARISON IS PER SUB-WINDOW, not a maximum over the whole region,
    and that distinction is the whole content of this function. A maximum
    over every cell answers "did ANY window length at the native rate ever
    frame a real event", which on region A is yes - one cell in nine - and
    reads as a pass. What is actually being asked is "can a production run
    at a single window length frame these events THROUGHOUT the region", and
    that needs each sub-window's window-arm cells compared against the rate
    arm's on the SAME samples.

    A cell frames the events if its deepest event is within
    `DEPTH_AGREEMENT` of the deepest the rate arm found on the same
    sub-window. A cell that timed out is neither a pass nor a fail: it is
    counted separately, because "too slow to measure" and "measuring the
    wrong thing" are different problems with different remedies.
    """
    region = lionsmane12.REGIONS[region] if isinstance(region, str) else region
    mine = [c for c in cells if c.get("region") == region.key]

    per_sub_window, agreeing, disagreeing = {}, 0, 0
    for start in sorted({c["sub_start_idx"] for c in mine}):
        here = [c for c in mine if c["sub_start_idx"] == start]
        rate_best = max((c["max_depth_mv"] for c in here
                         if c["arm"] == "rate" and c.get("n")), default=0.0)
        rows = []
        for cell in [c for c in here if c["arm"] == "window"]:
            if cell.get("timed_out"):
                rows.append({"window_samples": cell["window_samples"],
                             "outcome": "timed_out"})
                continue
            if rate_best <= 0:
                # A follow-up pass may re-run the window arm alone, and then
                # there is nothing on these samples to judge "deep enough"
                # against. Scoring it anyway would divide by a missing
                # reference and call every cell a pass - which is exactly
                # what the first version of this did when the follow-up ran
                # with the rate arm switched off.
                rows.append({"window_samples": cell["window_samples"],
                             "max_depth_mv": cell.get("max_depth_mv"),
                             "outcome": "no_rate_arm_to_compare_against"})
                continue
            if not cell.get("n"):
                rows.append({"window_samples": cell["window_samples"],
                             "outcome": "no_events"})
                disagreeing += 1
                continue
            ratio = (rate_best / cell["max_depth_mv"]
                     if cell["max_depth_mv"] > 0 else float("inf"))
            frames = bool(ratio <= DEPTH_AGREEMENT)
            agreeing += int(frames)
            disagreeing += int(not frames)
            rows.append({"window_samples": cell["window_samples"],
                         "max_depth_mv": cell["max_depth_mv"],
                         "rate_arm_max_depth_mv": rate_best,
                         "ratio": float(ratio),
                         "outcome": "frames_the_events" if frames
                                    else "measures_noise"})
        per_sub_window[str(start)] = {"rate_arm_max_depth_mv": rate_best,
                                      "window_cells": rows}

    timed_out = sum(1 for c in mine if c.get("timed_out"))
    completed = agreeing + disagreeing
    fraction = (agreeing / completed) if completed else 0.0
    has_reference = any(c["arm"] == "rate" and c.get("n") for c in mine)
    usable = bool(has_reference and completed and fraction >= 0.5
                  and timed_out <= completed)

    if not has_reference:
        return {
            "region": region.key,
            "judged": False,
            "n_window_cells_timed_out": timed_out,
            "per_sub_window": per_sub_window,
            "window_arm_measures_the_events": False,
            "note": "NOT JUDGED — this pass ran the window arm alone, so "
                    "there is no independent measurement of how deep these "
                    "sub-windows' events really are. Read it beside the "
                    "pass that did run the rate arm.",
        }

    return {
        "region": region.key,
        "judged": True,
        "depth_agreement_factor": DEPTH_AGREEMENT,
        "n_window_cells_framing_the_events": agreeing,
        "n_window_cells_measuring_noise": disagreeing,
        "n_window_cells_timed_out": timed_out,
        "fraction_of_completed_cells_framing_the_events": float(fraction),
        "per_sub_window": per_sub_window,
        "window_arm_measures_the_events": usable,
        "note": (
            f"{agreeing} of {completed} completed window-arm cells frame the "
            f"same events the rate arm finds, and {timed_out} did not "
            "complete. The native rate can be used here."
            if usable else
            f"only {agreeing} of {completed} completed window-arm cells frame "
            f"the events the rate arm finds on the same samples, and "
            f"{timed_out} did not complete at all. At the native rate this "
            "region is measured inconsistently: some sub-windows return the "
            "real events and others return noise excursions one to two "
            "orders shallower."),
    }
