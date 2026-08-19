"""
store.py
=========
The drop-motif event store: one CSV table, one packed array file, one
manifest, per detection run.

This is the deliverable, not a side effect. Two claims rest on it, and
both are only true if the reload path is complete and never touches the
recording:

  - "the plots can be adjusted without rerunning any algorithms" - so the
    figure code takes this store as its input, never a channel;
  - "enough data to satisfy the idea of a data card" - so the manifest
    carries every parameter, every rejection count and the measured
    distributions, and section 7's prose is a transcription of it rather
    than a re-analysis.

Layout, per run:

    DATA/derived/drop_motifs/<recording_id>/
        events.csv        one row per drop
        snippets.npz      every snippet, keyed by event_id
        manifest.json     parameters, counts, distributions, timing

One packed `.npz` per recording rather than one file per event: these runs
produce tens of events, not thousands, and a single archive keeps the
store to three files that can be copied or attached as a unit. It also
makes the "does every row have a snippet" invariant checkable in one
`set()` comparison rather than a directory walk.

Indices on disk are ABSOLUTE in the source channel. A run over a cropped
span (M2_aug's 336-346 h out of 721 h) still writes indices that index the
whole `.npy`, so the original array can be re-sliced exactly if somebody
later wants more context than was materialised. That is the real safety
net; the stored snippet is the convenience copy, independent of whether
`DATA/` is reachable at all.

Amplitudes are stored in mV, matching `motif_report.transform_snippet`'s
convention, so a number read off this table is directly comparable to one
read off `Plots/motif_families/`.

No plotting library - CLAUDE.md rule 1.
"""

import json
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

from Working.Detection.drop_motifs.detect import params_as_dict

EVENTS_FILENAME = "events.csv"
SNIPPETS_FILENAME = "snippets.npz"
MANIFEST_FILENAME = "manifest.json"

# The column order the CSV is written in. Kept as a module constant rather
# than derived from the dataclass so a reader (and a test) has one place to
# look for the contract, and so adding a field to `DropEvent` cannot
# silently reorder a table somebody has already cited.
EVENT_TABLE_COLUMNS = [
    # `span_key` identifies WHICH analysed span an event came from, and is
    # not the same thing as `recording_id`: three of the shipped spans sit
    # on recording 1 at wildly different time scales, so grouping figures
    # by recording would merge sets that were deliberately parameterised
    # apart. Every per-group figure keys on this.
    "event_id", "span_key", "span_label",
    "recording_id", "source_file", "channel", "fs",
    "up_region_start_idx", "up_region_end_idx",
    "up_region_start_h", "up_region_end_h",
    "onset_idx", "onset_h", "onset_slope_raw",
    "trough_idx", "trough_h",
    "snippet_start_idx", "snippet_end_idx", "snippet_key",
    "drop_depth_mv", "fall_duration_s", "peak_to_peak_mv",
    "pre_context_s", "post_context_s",
    "detrend_window_s", "segment_seconds", "same_fraction", "slope_sigma",
    "dsax_threshold_mode", "dsax_trend_estimator",
    "random_seed", "cluster_id",
]

# Columns that must survive a CSV round trip as integers. A float
# `onset_idx` does not raise when it slices an array - it raises much
# later, somewhere else, or not at all.
_INT_COLUMNS = [
    "recording_id", "channel",
    "up_region_start_idx", "up_region_end_idx",
    "onset_idx", "trough_idx",
    "snippet_start_idx", "snippet_end_idx",
    "random_seed", "cluster_id",
]

UNASSIGNED_CLUSTER = -1


def event_id(recording_id, onset_idx):
    """Stable, human-readable, and a valid `.npz` key.

    Keyed on the absolute onset index rather than on a sequence number, so
    the same event keeps the same id across reruns with different
    parameters - which is what makes two runs comparable at all. The
    recording id plus an absolute index is unique across spans too,
    because two spans on one recording do not overlap.
    """
    return f"r{int(recording_id)}_i{int(onset_idx)}"


# -- writing ---------------------------------------------------------------

def write_run(out_dir, result, x, *, fs, recording_id, source_file, channel,
              span_start_idx=0, span_key=None, span_label=None, extra=None):
    """Write one detection run's table, snippets and manifest.

    `x` is the array detection ran on, in native units (volts).
    `span_start_idx` is where that array starts inside the source channel;
    every index written out is shifted by it.

    Returns the three paths written, so a caller can print them.
    """
    os.makedirs(out_dir, exist_ok=True)
    x = np.asarray(x, dtype=float).ravel()
    offset = int(span_start_idx)

    rows, arrays = [], {}
    for event in result.events:
        absolute_onset = event.onset_idx + offset
        key = event_id(recording_id, absolute_onset)
        start, end = event.snippet_start_idx, event.snippet_end_idx

        arrays[f"{key}__raw_mv"] = x[start:end] * 1000.0
        arrays[f"{key}__detrended_mv"] = (
            np.asarray(result.x_detrended[start:end], dtype=float) * 1000.0)
        # Absolute seconds in the channel, so a snippet plotted on its own
        # can still be located in the recording without the table.
        arrays[f"{key}__t_s"] = (np.arange(start, end) + offset) / float(fs)

        rows.append({
            "event_id": key,
            "span_key": span_key or f"r{int(recording_id)}",
            "span_label": span_label or source_file,
            "recording_id": int(recording_id),
            "source_file": source_file,
            "channel": int(channel),
            "fs": float(fs),
            "up_region_start_idx": event.up_region_start_idx + offset,
            "up_region_end_idx": event.up_region_end_idx + offset,
            "up_region_start_h": (event.up_region_start_idx + offset) / fs / 3600.0,
            "up_region_end_h": (event.up_region_end_idx + offset) / fs / 3600.0,
            "onset_idx": absolute_onset,
            "onset_h": absolute_onset / fs / 3600.0,
            "onset_slope_raw": event.onset_slope_raw,
            "trough_idx": event.trough_idx + offset,
            "trough_h": (event.trough_idx + offset) / fs / 3600.0,
            "snippet_start_idx": start + offset,
            "snippet_end_idx": end + offset,
            "snippet_key": key,
            "drop_depth_mv": event.drop_depth_mv,
            "fall_duration_s": event.fall_duration_s,
            "peak_to_peak_mv": event.peak_to_peak_mv,
            "pre_context_s": (event.onset_idx - start) / fs,
            "post_context_s": (end - event.trough_idx) / fs,
            "detrend_window_s": event.detrend_window_s,
            "segment_seconds": event.segment_seconds,
            "same_fraction": event.same_fraction,
            "slope_sigma": event.slope_sigma,
            "dsax_threshold_mode": event.dsax_threshold_mode,
            "dsax_trend_estimator": event.dsax_trend_estimator,
            "random_seed": result.params.random_seed if result.params else -1,
            "cluster_id": UNASSIGNED_CLUSTER,
        })

    events_path = os.path.join(out_dir, EVENTS_FILENAME)
    pd.DataFrame(rows, columns=EVENT_TABLE_COLUMNS).to_csv(events_path, index=False)

    snippets_path = os.path.join(out_dir, SNIPPETS_FILENAME)
    np.savez_compressed(snippets_path, **arrays)

    manifest_path = os.path.join(out_dir, MANIFEST_FILENAME)
    manifest = build_manifest(result, rows, fs=fs, recording_id=recording_id,
                              source_file=source_file, channel=channel,
                              span_start_idx=offset, span_samples=len(x),
                              span_key=span_key, span_label=span_label,
                              extra=extra)
    with open(manifest_path, "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, indent=2, sort_keys=False)

    return {"events": events_path, "snippets": snippets_path,
            "manifest": manifest_path}


def build_manifest(result, rows, *, fs, recording_id, source_file, channel,
                   span_start_idx, span_samples, span_key=None,
                   span_label=None, extra=None):
    """The data card's raw material.

    Distributions are summarised as five-number-ish dicts rather than
    dumped in full, because the point is a figure caption and a table row,
    not a second copy of the event table. Everything here should be
    quotable verbatim; nothing here should need re-deriving from the CSV.
    """
    depths = [r["drop_depth_mv"] for r in rows]
    falls = [r["fall_duration_s"] for r in rows]
    p2p = [r["peak_to_peak_mv"] for r in rows]

    return {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "span_key": span_key,
        "span_label": span_label,
        "recording": {
            "id": int(recording_id),
            "source_file": source_file,
            "channel": int(channel),
            "fs": float(fs),
            "span_start_idx": int(span_start_idx),
            "span_samples": int(span_samples),
            "span_start_h": span_start_idx / fs / 3600.0,
            "span_end_h": (span_start_idx + span_samples) / fs / 3600.0,
        },
        "params": params_as_dict(result.params) if result.params else {},
        "counts": dict(result.counts),
        "diagnostics": dict(result.diagnostics),
        "distributions": {
            "drop_depth_mv": _summary(depths),
            "fall_duration_s": _summary(falls),
            "peak_to_peak_mv": _summary(p2p),
        },
        # Explicit rather than inferable from a count of zero, because
        # "found nothing" and "was never run" must not look alike on disk
        # (work order 1.8).
        "empty": len(rows) == 0,
        "extra": dict(extra or {}),
    }


def _summary(values):
    if not values:
        return {"n": 0}
    a = np.asarray(values, dtype=float)
    return {
        "n": int(a.size),
        "min": float(a.min()), "p25": float(np.percentile(a, 25)),
        "median": float(np.median(a)), "p75": float(np.percentile(a, 75)),
        "max": float(a.max()), "mean": float(a.mean()), "sd": float(a.std()),
    }


# -- reading ---------------------------------------------------------------

def load_events(out_dir):
    """The event table as a list of dicts, with integer columns intact.

    A list of dicts rather than the DataFrame because every consumer here
    iterates events; returning the frame would invite `.iloc` indexing that
    silently reorders against the `.npz` keys.
    """
    path = os.path.join(out_dir, EVENTS_FILENAME)
    if not os.path.exists(path):
        raise FileNotFoundError(
            f"No event table at {path}. A run that found nothing still "
            "writes one - if this is missing, detection was never run here.")
    frame = pd.read_csv(path)
    if frame.empty:
        return []
    for column in _INT_COLUMNS:
        if column in frame.columns:
            frame[column] = frame[column].astype(np.int64)
    return frame.to_dict("records")


def load_events_frame(out_dir):
    """The same table as a DataFrame, for the summary tables in section 7."""
    rows = load_events(out_dir)
    return pd.DataFrame(rows, columns=EVENT_TABLE_COLUMNS)


def load_snippets(out_dir):
    """`{event_id: {"raw_mv", "detrended_mv", "t_s"}}`.

    Reads the `.npz` and nothing else - no database, no channel, no
    `npy_path`. That is the property `--replot-from` depends on and
    `tests/test_drop_motifs_store.py` asserts by deleting the source array
    before calling this.
    """
    path = os.path.join(out_dir, SNIPPETS_FILENAME)
    if not os.path.exists(path):
        raise FileNotFoundError(f"No snippet store at {path}.")
    out = {}
    with np.load(path) as archive:
        for name in archive.files:
            key, _, field = name.rpartition("__")
            out.setdefault(key, {})[field] = np.asarray(archive[name])
    return out


def load_manifest(out_dir):
    path = os.path.join(out_dir, MANIFEST_FILENAME)
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def load_run(out_dir):
    """Everything one run wrote, in one call - the `--replot-from` entry."""
    return {"dir": out_dir, "events": load_events(out_dir),
            "snippets": load_snippets(out_dir), "manifest": load_manifest(out_dir)}


def load_runs(out_dirs):
    """Several runs pooled into one event list plus one snippet dict.

    The pooled set is what the combined cross-dataset dendrogram is built
    over. Event ids already carry the recording id, so pooling cannot
    collide.
    """
    events, snippets, manifests = [], {}, {}
    for out_dir in out_dirs:
        run = load_run(out_dir)
        events.extend(run["events"])
        snippets.update(run["snippets"])
        manifests[out_dir] = run["manifest"]
    return {"events": events, "snippets": snippets, "manifests": manifests}


# -- updating --------------------------------------------------------------

def assign_clusters(out_dir, cluster_by_event_id):
    """Write cluster labels back into an existing table, in place.

    Rewrites only `cluster_id`; every other column is read and written
    unchanged, so a clustering rerun cannot perturb the detection record
    it is annotating. Events absent from the mapping keep their current
    label rather than being reset, which is what allows a cluster
    assignment over a pooled set to be written back into each recording's
    own table.
    """
    path = os.path.join(out_dir, EVENTS_FILENAME)
    frame = pd.read_csv(path)
    if frame.empty:
        return 0
    updated = frame["event_id"].map(cluster_by_event_id)
    frame["cluster_id"] = updated.fillna(frame["cluster_id"]).astype(np.int64)
    frame.to_csv(path, index=False)
    return int(updated.notna().sum())
