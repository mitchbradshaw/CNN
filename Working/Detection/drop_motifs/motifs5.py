"""
motifs5.py
===========
The motif library: every extracted window, on disk, in a form the existing
clustering and gradient code already reads.

Why this shape
--------------
`cluster.py` and `gradients.py` were written against `store.py`'s output -
a table of event dicts plus an archive of per-event arrays keyed by
`event_id`, carrying `raw_mv`, `detrended_mv` and `t_s`. Writing the
five-stage windows in the SAME shape means `event_waveform`,
`feature_matrix`, `build_linkage`, `distance_matrix`, `event_gradients`
and `rose_data` all work on them unchanged. Inventing a second format
would mean reimplementing every one of those, and then having two
definitions of "a motif" in one repository.

The differences from `store.py` are declared rather than smuggled:

  - `snippet_start_idx` / `snippet_end_idx` carry the WINDOW bounds, which
    are a different quantity from the three-stage snippet (bracketed on
    UP runs rather than sized as multiples of the fall). The names are
    kept because the consumers index by them; the manifest records which
    detector produced the file so the two are never confused.
  - each row carries `purity` (how many falls its window holds) and
    `is_pure`, so a figure can exclude impure windows without recomputing
    them, and `rise_frac_used`, so a window that needed the tightening
    ladder is visible.
  - rows from every span live in ONE store, keyed by a globally unique
    `event_id`, because the across-all-spans dendrogram and rose need
    exactly that and building it by concatenating per-span stores would
    make the pooled figure depend on load order.

Bulk arrays never enter the database (CLAUDE.md rule 4): this is an `.npz`
on disk plus a `.csv` index, referenced by path.
"""

import json
import os

import numpy as np

# The store's own version, written into the manifest. A consumer that
# cares which detector produced a window has one field to read rather than
# a heuristic on the column set.
STORE_KIND = "drop_motifs5"
STORE_VERSION = 1

UNASSIGNED_CLUSTER = -1

EVENTS_CSV = "motifs.csv"
SNIPPETS_NPZ = "motifs.npz"
MANIFEST_JSON = "manifest.json"


def motif_id(catalogue_id, recording_id, absolute_onset):
    """Globally unique across spans.

    The catalogue ID leads because two spans on one recording can overlap
    (ID 20 is a sub-span of ID 1, ID 21 of ID 3), so a recording-and-onset
    key would collide between them and silently drop one of the pair from
    the pooled store.
    """
    return f"id{int(catalogue_id):03d}_r{int(recording_id)}_{int(absolute_onset)}"


def rows_and_arrays(result, x, purity, *, catalogue_id, recording_id, fs,
                    source_file, channel, span_offset=0, span_label=None,
                    span_key=None):
    """One span's events as `(rows, arrays)` ready to merge into a store."""
    x = np.asarray(x, dtype=float).ravel()
    detrended = np.asarray(result.x_detrended, dtype=float)
    offset = int(span_offset)
    fs = float(fs)

    rows, arrays = [], {}
    for index, event in enumerate(result.events):
        absolute_onset = event.onset_idx + offset
        key = motif_id(catalogue_id, recording_id, absolute_onset)
        start, end = event.window_start_idx, event.window_end_idx
        falls = int(purity[index]) if index < len(purity) else 1

        arrays[f"{key}__raw_mv"] = x[start:end] * 1000.0
        arrays[f"{key}__detrended_mv"] = detrended[start:end] * 1000.0
        # Absolute seconds in the channel, so a window plotted on its own
        # can still be located in the recording without the table.
        arrays[f"{key}__t_s"] = (np.arange(start, end) + offset) / fs

        rows.append({
            "event_id": key,
            "catalogue_id": int(catalogue_id),
            "span_key": span_key or f"id{int(catalogue_id):03d}",
            "span_label": span_label or source_file,
            "recording_id": int(recording_id),
            "source_file": source_file,
            "channel": int(channel),
            "fs": fs,
            "morphology": event.morphology,
            "trigger": event.trigger,
            "up_region_start_idx": (event.up_region_start_idx + offset
                                    if event.up_region_start_idx >= 0 else -1),
            "up_region_end_idx": (event.up_region_end_idx + offset
                                  if event.up_region_end_idx >= 0 else -1),
            "onset_idx": absolute_onset,
            "onset_h": absolute_onset / fs / 3600.0,
            "trough_idx": event.trough_idx + offset,
            "trough_h": (event.trough_idx + offset) / fs / 3600.0,
            # WINDOW bounds under these names, because that is what the
            # existing consumers index by. See the module docstring.
            "snippet_start_idx": start + offset,
            "snippet_end_idx": end + offset,
            "snippet_key": key,
            "onset_slope_raw": event.onset_slope_raw,
            "max_slope_raw": event.max_slope_raw,
            "drop_depth_mv": event.drop_depth_mv,
            "rise_height_mv": event.rise_height_mv,
            "fall_duration_s": event.fall_duration_s,
            "peak_to_peak_mv": event.peak_to_peak_mv,
            "fall_dominance": event.fall_dominance,
            "rise_frac_used": event.rise_frac_used,
            "pre_context_s": (event.onset_idx - start) / fs,
            "post_context_s": (end - event.trough_idx) / fs,
            "detrend_window_s": event.detrend_window_s,
            "segment_seconds": event.segment_seconds,
            "same_fraction": event.same_fraction,
            "slope_sigma": event.slope_sigma,
            # The grade, carried so a figure can exclude impure windows
            # without re-running the detector to find out which they are.
            "purity": falls,
            "is_pure": int(falls == 1),
            "cluster_id": UNASSIGNED_CLUSTER,
        })
    return rows, arrays


def write_store(out_dir, rows, arrays, manifest_extra=None):
    """Write the whole library: one CSV, one NPZ, one manifest."""
    os.makedirs(out_dir, exist_ok=True)
    import csv

    events_path = os.path.join(out_dir, EVENTS_CSV)
    if rows:
        fieldnames = list(rows[0])
        with open(events_path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    else:
        open(events_path, "w", encoding="utf-8").close()

    snippets_path = os.path.join(out_dir, SNIPPETS_NPZ)
    np.savez_compressed(snippets_path, **arrays)

    pure = sum(r["is_pure"] for r in rows)
    manifest = {
        "kind": STORE_KIND,
        "version": STORE_VERSION,
        "n_motifs": len(rows),
        "n_pure": int(pure),
        "n_impure": len(rows) - int(pure),
        "spans": sorted({int(r["catalogue_id"]) for r in rows}),
        "per_span": {
            str(cid): sum(1 for r in rows if r["catalogue_id"] == cid)
            for cid in sorted({int(r["catalogue_id"]) for r in rows})
        },
        "empty": not rows,
    }
    manifest.update(manifest_extra or {})
    manifest_path = os.path.join(out_dir, MANIFEST_JSON)
    with open(manifest_path, "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2, default=float)

    return events_path, snippets_path, manifest_path


# -- reading it back -------------------------------------------------------

_INT_COLUMNS = {
    "catalogue_id", "recording_id", "channel", "up_region_start_idx",
    "up_region_end_idx", "onset_idx", "trough_idx", "snippet_start_idx",
    "snippet_end_idx", "purity", "is_pure", "cluster_id",
}


def load_events(out_dir):
    """The table, with index columns as ints.

    Integers stay integers deliberately: an index read back as a float
    silently becomes a float array subscript later, and numpy's error for
    that arrives a long way from here.
    """
    import csv

    path = os.path.join(out_dir, EVENTS_CSV)
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    for row in rows:
        for key, value in list(row.items()):
            if key in _INT_COLUMNS:
                row[key] = int(float(value))
            elif key in {"event_id", "span_key", "span_label", "source_file",
                         "snippet_key", "morphology", "trigger"}:
                continue
            else:
                try:
                    row[key] = float(value)
                except (TypeError, ValueError):
                    pass
    return rows


def load_snippets(out_dir):
    """`{event_id: {"raw_mv", "detrended_mv", "t_s"}}`."""
    path = os.path.join(out_dir, SNIPPETS_NPZ)
    archive = np.load(path)
    out = {}
    for name in archive.files:
        key, _, field = name.partition("__")
        out.setdefault(key, {})[field] = archive[name]
    return out


def load_manifest(out_dir):
    with open(os.path.join(out_dir, MANIFEST_JSON), encoding="utf-8") as handle:
        return json.load(handle)


def load_store(out_dir, pure_only=False):
    """`(events, snippets, manifest)`.

    `pure_only` is the flag every clustering and rose figure passes: an
    impure window holds more than one fall, so its shape is a statement
    about a burst rather than about a motif, and averaging it into a
    family is how the original bad dendrogram happened.
    """
    events = load_events(out_dir)
    if pure_only:
        events = [e for e in events if e["is_pure"]]
    return events, load_snippets(out_dir), load_manifest(out_dir)
